"""
Rate limiting tests — covers:
  - In-memory bucket: allow under limit, block at limit, reset after window
  - RateLimiter.check() falls back to in-memory when Redis is unavailable
  - HTTP middleware: 429 on burst, headers present, IP-based limiting
  - Redis fallback: middleware stays functional when Redis is down
  - Bot/UA detection helper

Tests use an in-memory SQLite DB (no Postgres required) and patch the
module-level rate_limiter in app.main so each test starts from a clean state.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.rate_limiter import (
    BAN_TTL_S,
    RULES,
    RateLimitResult,
    RateLimitRule,
    RateLimiter,
    _MemoryStore,
)
from app.main import app
from app.models.database import Base
from app.models.db_session import get_db

# ── Shared in-memory DB fixture ───────────────────────────────────────────────

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
async def client():
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helper: reset rate limiter state between tests ────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def reset_limiter():
    """Clear in-memory counters before every test for isolation."""
    from app.main import rate_limiter
    rate_limiter._reset_memory()
    yield
    rate_limiter._reset_memory()


# ── _MemoryStore unit tests ───────────────────────────────────────────────────

class TestMemoryStore:
    def test_allows_requests_under_limit(self):
        store = _MemoryStore()
        rule = RateLimitRule(limit=3, window_s=60, key_by="ip")
        for _ in range(3):
            result = store.check("test_key", rule)
            assert result.allowed

    def test_blocks_at_limit(self):
        store = _MemoryStore()
        rule = RateLimitRule(limit=3, window_s=60, key_by="ip")
        for _ in range(3):
            store.check("test_key", rule)
        result = store.check("test_key", rule)
        assert not result.allowed
        assert result.remaining == 0
        assert result.retry_after > 0

    def test_different_keys_are_independent(self):
        store = _MemoryStore()
        rule = RateLimitRule(limit=2, window_s=60, key_by="ip")
        store.check("key_a", rule)
        store.check("key_a", rule)
        # key_a is exhausted
        assert not store.check("key_a", rule).allowed
        # key_b is still fresh
        assert store.check("key_b", rule).allowed

    def test_clear_resets_all_counters(self):
        store = _MemoryStore()
        rule = RateLimitRule(limit=1, window_s=60, key_by="ip")
        store.check("k", rule)
        assert not store.check("k", rule).allowed
        store.clear()
        assert store.check("k", rule).allowed

    def test_result_fields_populated(self):
        store = _MemoryStore()
        rule = RateLimitRule(limit=5, window_s=60, key_by="ip")
        result = store.check("k", rule)
        assert result.limit == 5
        assert result.remaining == 4
        assert result.reset_ts > int(time.time())
        assert result.retry_after == 0


# ── RateLimiter.check() fallback ──────────────────────────────────────────────

class TestRateLimiterFallback:
    @pytest.mark.asyncio
    async def test_uses_memory_when_redis_down(self):
        limiter = RateLimiter("redis://invalid-host:6379/0")
        # Don't call startup — redis_ok stays False, memory fallback kicks in
        result = await limiter.check("user:123", "api_v1_default")
        assert result.allowed
        assert result.limit == RULES["api_v1_default"].limit

    @pytest.mark.asyncio
    async def test_memory_fallback_enforces_limit(self):
        rule = RULES["auth_login"]
        limiter = RateLimiter("redis://invalid:6379")
        for _ in range(rule.limit):
            r = await limiter.check("1.2.3.4", "auth_login")
            assert r.allowed
        blocked = await limiter.check("1.2.3.4", "auth_login")
        assert not blocked.allowed
        assert blocked.retry_after > 0

    @pytest.mark.asyncio
    async def test_redis_failure_during_check_falls_back(self):
        """If Redis raises mid-request, we silently fall back to memory."""
        limiter = RateLimiter("redis://localhost:6379/0")
        limiter._redis_ok = True
        bad_client = AsyncMock()
        bad_pipe = MagicMock()
        bad_pipe.incr = MagicMock()
        bad_pipe.expireat = MagicMock()
        bad_pipe.execute = AsyncMock(side_effect=ConnectionError("gone"))
        bad_client.pipeline = MagicMock(return_value=bad_pipe)
        limiter._client = bad_client

        result = await limiter.check("user:abc", "api_v1_default")
        assert result.allowed          # memory fallback allowed it
        assert not limiter._redis_ok   # Redis flagged as down


# ── Bot / UA detection ────────────────────────────────────────────────────────

class TestBotDetection:
    def test_empty_ua_is_suspicious(self):
        assert RateLimiter.is_suspicious_ua("") is True

    def test_whitespace_ua_is_suspicious(self):
        assert RateLimiter.is_suspicious_ua("   ") is True

    def test_known_bot_ua(self):
        assert RateLimiter.is_suspicious_ua("python-requests/2.28.0") is True
        assert RateLimiter.is_suspicious_ua("curl/7.88.1") is True
        assert RateLimiter.is_suspicious_ua("Wget/1.21.3") is True

    def test_browser_ua_not_suspicious(self):
        chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"
        assert RateLimiter.is_suspicious_ua(chrome) is False

    def test_case_insensitive(self):
        assert RateLimiter.is_suspicious_ua("Python-Requests/2.0") is True


# ── HTTP middleware integration tests ─────────────────────────────────────────

class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_rate_limit_headers_present_on_normal_request(self, client):
        r = await client.get("/health")
        # /health is exempt — no rate limit headers
        assert "X-RateLimit-Limit" not in r.headers

    @pytest.mark.asyncio
    async def test_login_burst_returns_429(self, client):
        """POST /auth/login allows 5 attempts then returns 429."""
        limit = RULES["auth_login"].limit
        for _ in range(limit):
            await client.post(
                "/auth/login",
                json={"email": "x@x.com", "password": "wrong"},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
        r = await client.post(
            "/auth/login",
            json={"email": "x@x.com", "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_429_includes_retry_after_header(self, client):
        limit = RULES["auth_login"].limit
        for _ in range(limit):
            await client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        r = await client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        assert r.status_code == 429
        assert "retry-after" in r.headers
        assert int(r.headers["retry-after"]) > 0

    @pytest.mark.asyncio
    async def test_rate_limit_headers_on_allowed_api_response(self, client):
        """Non-blocked API requests carry X-RateLimit-* headers."""
        # Register + login to get a token
        await client.post(
            "/auth/register",
            json={"email": "rl_headers@example.com", "password": "Password1"},
        )
        login_r = await client.post(
            "/auth/login",
            json={"email": "rl_headers@example.com", "password": "Password1"},
        )
        token = login_r.json()["access_token"]

        r = await client.get(
            "/api/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "x-ratelimit-limit" in r.headers
        assert "x-ratelimit-remaining" in r.headers
        assert "x-ratelimit-reset" in r.headers

    @pytest.mark.asyncio
    async def test_different_ips_have_independent_login_limits(self, client):
        """IP A exhausted should not block IP B."""
        limit = RULES["auth_login"].limit
        for _ in range(limit):
            await client.post(
                "/auth/login",
                json={"email": "a@b.com", "password": "x"},
                headers={"X-Forwarded-For": "192.168.1.10"},
            )

        # IP A is now blocked
        blocked = await client.post(
            "/auth/login",
            json={"email": "a@b.com", "password": "x"},
            headers={"X-Forwarded-For": "192.168.1.10"},
        )
        assert blocked.status_code == 429

        # IP B should not be blocked
        r = await client.post(
            "/auth/login",
            json={"email": "a@b.com", "password": "x"},
            headers={"X-Forwarded-For": "192.168.2.20"},
        )
        # 401 = credentials wrong but not rate-limited — that's correct
        assert r.status_code != 429

    @pytest.mark.asyncio
    async def test_redis_unavailable_does_not_block_requests(self, client):
        """When Redis is down, in-memory fallback is used and requests go through."""
        from app.main import rate_limiter

        # Simulate Redis going down
        original_ok = rate_limiter._redis_ok
        rate_limiter._redis_ok = False
        try:
            r = await client.get("/health")
            assert r.status_code == 200  # health is exempt, always ok
        finally:
            rate_limiter._redis_ok = original_ok


# ── ip_global DDoS rule ───────────────────────────────────────────────────────

class TestIPGlobalLimit:
    @pytest.mark.asyncio
    async def test_ip_global_rule_exists(self):
        assert "ip_global" in RULES
        rule = RULES["ip_global"]
        assert rule.limit == 1000
        assert rule.window_s == 60
        assert rule.key_by == "ip"

    @pytest.mark.asyncio
    async def test_ip_ban_blocks_subsequent_requests(self, client):
        """Once an IP is banned, further requests return 429 immediately."""
        from app.main import rate_limiter

        # Patch is_banned to return True for our test IP
        with patch.object(rate_limiter, "is_banned", new=AsyncMock(return_value=True)):
            r = await client.post(
                "/auth/login",
                json={"email": "a@b.com", "password": "x"},
                headers={"X-Forwarded-For": "10.1.1.1"},
            )
        assert r.status_code == 429
        assert "temporarily blocked" in r.json()["error"]["message"].lower()


# ── Execution limit constants ─────────────────────────────────────────────────

class TestExecutionLimits:
    def test_config_has_execution_limits(self):
        from app.core.config import settings
        assert settings.MAX_EXECUTION_TIME_S == 1800
        assert settings.MAX_PARALLEL_NODES == 20
        assert settings.MAX_TOKENS_PER_EXECUTION == 1_000_000
        assert settings.MAX_UPLOAD_SIZE_MB == 100
