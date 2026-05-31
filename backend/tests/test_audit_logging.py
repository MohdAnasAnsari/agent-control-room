"""
Phase 4.4 tests — audit logging, security alerts, metrics, admin dashboard.

All tests use an in-memory SQLite DB; no Postgres or Redis required.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import AuditAction, AuditLogger, audit, severity_for_action
from app.core.metrics_collector import MetricsCollector, _percentile
from app.main import app
from app.models.database import AuditLog, Base, User
from app.models.db_session import get_db

# ── Shared in-memory DB ───────────────────────────────────────────────────────

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
_Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _Session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _create_tables():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    async with _Session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_admin(db: AsyncSession, email: str = "admin@example.com") -> User:
    from app.core.security import hash_password
    user = User(email=email, hashed_password=hash_password("Password1"), role="admin")
    db.add(user)
    await db.flush()
    return user


async def _register_login(client: AsyncClient, email: str, password: str = "Password1"):
    await client.post("/auth/register", json={"email": email, "password": password})
    r = await client.post("/auth/login", json={"email": email, "password": password})
    return r.json().get("access_token", "")


# ── audit() function tests ────────────────────────────────────────────────────

class TestAuditFunction:
    @pytest.mark.asyncio
    async def test_writes_record_to_db(self, db: AsyncSession):
        user_id = uuid4()
        await audit(db, AuditAction.AGENT_CREATE, user_id=user_id,
                    resource_type="agent", resource_id="abc123")
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.AGENT_CREATE)
        )).scalar_one_or_none()

        assert row is not None
        assert row.user_id == user_id
        assert row.resource_type == "agent"
        assert row.severity == "medium"

    @pytest.mark.asyncio
    async def test_severity_inferred_from_action(self, db: AsyncSession):
        await audit(db, AuditAction.USER_LOGIN, user_id=uuid4(), _skip_alert=True)
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.USER_LOGIN)
        )).scalar_one()
        assert row.severity == "high"

    @pytest.mark.asyncio
    async def test_explicit_severity_overrides_default(self, db: AsyncSession):
        await audit(db, AuditAction.AGENT_READ, user_id=uuid4(),
                    severity="critical", _skip_alert=True)
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.AGENT_READ)
        )).scalar_one()
        assert row.severity == "critical"

    @pytest.mark.asyncio
    async def test_failed_action_stored_with_success_false(self, db: AsyncSession):
        await audit(db, AuditAction.USER_LOGIN_FAIL, user_id=uuid4(),
                    success=False, detail={"email": "x@x.com"}, _skip_alert=True)
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.USER_LOGIN_FAIL)
        )).scalar_one()
        assert row.success is False


# ── severity_for_action() ─────────────────────────────────────────────────────

class TestSeverityMapping:
    def test_known_high_actions(self):
        assert severity_for_action(AuditAction.USER_LOGIN)   == "high"
        assert severity_for_action(AuditAction.API_KEY_CREATE) == "high"
        assert severity_for_action(AuditAction.WORKFLOW_EXECUTE) == "high"

    def test_known_medium_actions(self):
        assert severity_for_action(AuditAction.AGENT_CREATE)  == "medium"
        assert severity_for_action(AuditAction.WORKFLOW_CREATE) == "medium"

    def test_known_low_actions(self):
        assert severity_for_action(AuditAction.TOKEN_REFRESH)  == "low"
        assert severity_for_action(AuditAction.SETTINGS_CHANGE) == "low"

    def test_critical_action(self):
        assert severity_for_action(AuditAction.ACCOUNT_LOCKED) == "critical"

    def test_unknown_action_defaults_to_low(self):
        assert severity_for_action("some.unknown.action") == "low"


# ── AuditLogger class ─────────────────────────────────────────────────────────

class TestAuditLogger:
    @pytest.mark.asyncio
    async def test_log_method_writes_record(self, db: AsyncSession):
        logger = AuditLogger(db)
        uid = uuid4()
        await logger.log(AuditAction.WORKFLOW_CREATE, user_id=uid,
                         resource_type="workflow", resource_id="wf1")
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.WORKFLOW_CREATE,
                                   AuditLog.user_id == uid)
        )).scalar_one_or_none()
        assert row is not None

    @pytest.mark.asyncio
    async def test_log_high_forces_high_severity(self, db: AsyncSession):
        logger = AuditLogger(db)
        # agent.read normally = low
        await logger.log_high(AuditAction.AGENT_READ, user_id=uuid4())
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.AGENT_READ)
        )).scalar_one()
        assert row.severity == "high"

    @pytest.mark.asyncio
    async def test_log_critical_forces_critical_severity(self, db: AsyncSession):
        logger = AuditLogger(db)
        await logger.log_critical(AuditAction.SETTINGS_CHANGE, user_id=uuid4())
        await db.flush()

        from sqlalchemy import select
        row = (await db.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.SETTINGS_CHANGE)
        )).scalar_one()
        assert row.severity == "critical"


# ── Security alert service tests ──────────────────────────────────────────────

class TestAlertService:
    @pytest.mark.asyncio
    async def test_on_failed_login_below_threshold_no_lock(self, db: AsyncSession):
        """Under the threshold → account not locked."""
        from app.core.alert_service import AlertService, _lock_account

        svc = AlertService()
        # Only 2 failures — well below FAILED_LOGIN_THRESHOLD (5)
        user = await _create_admin(db, "nolockme@example.com")

        with patch("app.core.alert_service._count_recent_failures", new=AsyncMock(return_value=2)):
            await svc.on_failed_login(db, email="nolockme@example.com",
                                      ip="1.2.3.4", user_id=user.id)

        await db.refresh(user)
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_on_failed_login_at_threshold_locks_account(self, db: AsyncSession):
        from app.core.alert_service import AlertService

        svc = AlertService()
        user = await _create_admin(db, "lockme@example.com")

        with patch("app.core.alert_service._count_recent_failures",
                   new=AsyncMock(return_value=5)), \
             patch.object(svc, "_dispatch", new=AsyncMock()):
            await svc.on_failed_login(db, email="lockme@example.com",
                                      ip="1.2.3.4", user_id=user.id)

        await db.refresh(user)
        assert user.is_active is False

    @pytest.mark.asyncio
    async def test_on_new_ip_login_sends_alert(self, db: AsyncSession):
        from app.core.alert_service import AlertService

        svc = AlertService()
        uid = uuid4()

        with patch("app.core.alert_service._is_new_ip", new=AsyncMock(return_value=True)), \
             patch.object(svc, "_dispatch", new=AsyncMock()) as mock_dispatch:
            await svc.on_successful_login(db, user_id=uid,
                                          email="user@example.com", ip="99.88.77.66")

        mock_dispatch.assert_awaited_once()
        call_kwargs = mock_dispatch.await_args.kwargs
        assert "New IP" in call_kwargs.get("subject", "")

    @pytest.mark.asyncio
    async def test_dispatch_skipped_when_smtp_not_configured(self):
        from app.core.alert_service import AlertService

        svc = AlertService()
        svc._smtp_host = ""
        svc._alert_to  = "ops@example.com"
        svc._slack_webhook = ""

        # Should not raise even though SMTP is unconfigured
        await svc._dispatch("Test", "Body")

    @pytest.mark.asyncio
    async def test_on_metric_threshold_dispatches_alert(self):
        from app.core.alert_service import AlertService

        svc = AlertService()
        with patch.object(svc, "_dispatch", new=AsyncMock()) as mock_dispatch:
            await svc.on_metric_threshold(metric="error_rate", value=0.12,
                                          threshold=0.05, context="test run")

        mock_dispatch.assert_awaited_once()


# ── MetricsCollector tests ────────────────────────────────────────────────────

class TestMetricsCollector:
    def test_record_and_percentiles(self):
        mc = MetricsCollector()
        durations = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for d in durations:
            mc.record_request("/api/v1/agents", "GET", 200, float(d))

        snap = mc.percentiles(window_s=3600)
        assert snap.sample_count == 10
        assert snap.p50 > 0
        assert snap.p95 > snap.p50

    def test_error_rate_calculation(self):
        mc = MetricsCollector()
        for _ in range(8):
            mc.record_request("/api/v1/agents", "GET", 200, 50.0)
        for _ in range(2):
            mc.record_request("/api/v1/agents", "GET", 500, 50.0)

        rate = mc.error_rate(window_s=3600)
        assert abs(rate - 0.2) < 0.01   # 20%

    def test_empty_store_returns_zero_percentiles(self):
        mc = MetricsCollector()
        snap = mc.percentiles()
        assert snap.p50 == 0
        assert snap.p95 == 0

    def test_execution_failure_rate(self):
        mc = MetricsCollector()
        mc.record_execution(success=True)
        mc.record_execution(success=True)
        mc.record_execution(success=False)
        assert abs(mc.execution_failure_rate() - 1/3) < 0.01

    def test_prometheus_text_format(self):
        mc = MetricsCollector()
        mc.record_request("/api", "GET", 200, 100.0)
        text = mc.prometheus_text()
        assert "http_request_duration_ms" in text
        assert "http_error_rate" in text
        assert "quantile=" in text

    def test_summary_returns_all_fields(self):
        mc = MetricsCollector()
        mc.record_request("/api/v1/agents", "GET", 200, 150.0)
        s = mc.summary(window_s=3600)
        assert hasattr(s, "p50_ms")
        assert hasattr(s, "error_rate")
        assert hasattr(s, "requests_per_minute")

    @pytest.mark.asyncio
    async def test_check_alert_thresholds_fires_when_error_rate_high(self):
        from app.core.alert_service import AlertService

        mc = MetricsCollector()
        # Force 100% error rate
        for _ in range(10):
            mc.record_request("/api", "POST", 500, 100.0)

        mock_svc = AlertService()
        mock_svc._dispatch = AsyncMock()

        with patch("app.core.metrics_collector.alert_service", mock_svc):
            await mc.check_alert_thresholds()

        mock_svc._dispatch.assert_awaited()

    def test_percentile_helper(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert _percentile(data, 50) == 5.5
        assert _percentile(data, 99) >= 9.0
        assert _percentile([], 50) == 0.0


# ── Admin API integration tests ───────────────────────────────────────────────

class TestAdminEndpoints:
    @pytest.mark.asyncio
    async def test_audit_logs_requires_admin(self, client):
        """Regular users cannot access admin endpoints."""
        token = await _register_login(client, "regular@example.com")
        r = await client.get(
            "/api/v1/admin/audit-logs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_logs_unauthenticated(self, client):
        r = await client.get("/api/v1/admin/audit-logs")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_audit_logs_admin_access(self, client, db):
        # Manually create an admin user and log them in
        from app.core.security import hash_password
        admin = User(email="superadmin@example.com",
                     hashed_password=hash_password("Password1"),
                     role="admin")
        db.add(admin)
        await db.commit()

        r_login = await client.post(
            "/auth/login",
            json={"email": "superadmin@example.com", "password": "Password1"},
        )
        assert r_login.status_code == 200
        token = r_login.json()["access_token"]

        r = await client.get(
            "/api/v1/admin/audit-logs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body

    @pytest.mark.asyncio
    async def test_audit_logs_stats_admin_access(self, client, db):
        from app.core.security import hash_password
        admin2 = User(email="statsadmin@example.com",
                      hashed_password=hash_password("Password1"),
                      role="admin")
        db.add(admin2)
        await db.commit()

        r_login = await client.post(
            "/auth/login",
            json={"email": "statsadmin@example.com", "password": "Password1"},
        )
        token = r_login.json()["access_token"]

        r = await client.get(
            "/api/v1/admin/audit-logs/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "login_trends" in body
        assert "failed_auth_trends" in body
        assert "top_users" in body

    @pytest.mark.asyncio
    async def test_metrics_endpoint_admin_access(self, client, db):
        from app.core.security import hash_password
        m_admin = User(email="metricsadmin@example.com",
                       hashed_password=hash_password("Password1"),
                       role="admin")
        db.add(m_admin)
        await db.commit()

        token_r = await client.post(
            "/auth/login",
            json={"email": "metricsadmin@example.com", "password": "Password1"},
        )
        token = token_r.json()["access_token"]

        r = await client.get(
            "/api/v1/admin/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "p50_ms" in body
        assert "error_rate" in body
        assert "requests_per_minute" in body

    @pytest.mark.asyncio
    async def test_prometheus_endpoint(self, client, db):
        from app.core.security import hash_password
        p_admin = User(email="promadmin@example.com",
                       hashed_password=hash_password("Password1"),
                       role="admin")
        db.add(p_admin)
        await db.commit()

        token_r = await client.post(
            "/auth/login",
            json={"email": "promadmin@example.com", "password": "Password1"},
        )
        token = token_r.json()["access_token"]

        r = await client.get(
            "/api/v1/admin/metrics/prometheus",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "http_request_duration_ms" in r.text


# ── Data retention config tests ───────────────────────────────────────────────

class TestRetentionConfig:
    def test_retention_settings_exist(self):
        from app.core.config import settings
        assert settings.AUDIT_LOG_RETENTION_DAYS == 365
        assert settings.METRICS_RETENTION_DAYS == 90
        assert settings.EXECUTION_LOG_RETENTION_DAYS == 90

    def test_alert_threshold_settings(self):
        from app.core.config import settings
        assert settings.ALERT_ERROR_RATE == 0.05
        assert settings.ALERT_P95_LATENCY_MS == 5000.0
        assert settings.ALERT_EXEC_FAIL_RATE == 0.20
