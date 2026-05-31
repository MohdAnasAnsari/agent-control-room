"""
Phase 4.2 security tests.

Covers:
- Fernet EncryptedField round-trip and legacy fallback
- SensitiveFilter redaction (API keys, Bearer tokens, passwords, JWTs)
- Security response headers on every request
- HTTPS enforcement middleware
- JWT expiry rejection
- Unauthorized access blocked by auth middleware
- Audit log entries written on login / register / logout
"""

import logging
import os
import time
import unittest.mock as mock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── ensure a stable test encryption key before importing app modules ──────────
os.environ.setdefault("ENCRYPTION_KEY", "test_encryption_key_for_pytest_only_32b")
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_pytest_only_32bytes!")

from app.core.encryption import EncryptedField, _get_fernet
from app.core.logging_config import SensitiveFilter
from app.main import app
from app.models.database import AuditLog, Base
from app.models.db_session import get_db

# ── In-memory SQLite engine for tests ─────────────────────────────────────────
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


@pytest_asyncio.fixture
async def db():
    async with _Session() as session:
        yield session


# ── helpers ────────────────────────────────────────────────────────────────────

async def _register_and_login(client, email="sec@example.com", password="Password1"):
    await client.post("/auth/register", json={"email": email, "password": password})
    r = await client.post("/auth/login", json={"email": email, "password": password})
    return r.json()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Encryption / Decryption
# ══════════════════════════════════════════════════════════════════════════════

class TestEncryptedField:
    def test_encrypt_decrypt_round_trip(self):
        f = _get_fernet()
        plaintext = "Top secret system prompt"
        token = f.encrypt(plaintext.encode()).decode()
        recovered = f.decrypt(token.encode()).decode()
        assert recovered == plaintext

    def test_encrypted_field_write_produces_fernet_token(self):
        field = EncryptedField()
        result = field.process_bind_param("hello world", dialect=None)
        # Fernet tokens start with "gAAAAA" in base64url
        assert result is not None
        assert result.startswith("gAAAAA"), "Expected Fernet token prefix"

    def test_encrypted_field_read_decrypts(self):
        field = EncryptedField()
        encrypted = field.process_bind_param("secret value", dialect=None)
        decrypted = field.process_result_value(encrypted, dialect=None)
        assert decrypted == "secret value"

    def test_encrypted_field_none_passthrough(self):
        field = EncryptedField()
        assert field.process_bind_param(None, dialect=None) is None
        assert field.process_result_value(None, dialect=None) is None

    def test_encrypted_field_json_round_trip(self):
        field = EncryptedField(as_json=True)
        data = {"result": "ok", "tokens": 42, "nested": {"x": 1}}
        encrypted = field.process_bind_param(data, dialect=None)
        decrypted = field.process_result_value(encrypted, dialect=None)
        assert decrypted == data

    def test_encrypted_field_legacy_plaintext_fallback(self):
        """Unencrypted legacy values must be returned as-is."""
        field = EncryptedField()
        legacy = "plain old prompt not yet encrypted"
        result = field.process_result_value(legacy, dialect=None)
        assert result == legacy

    def test_encrypted_field_legacy_json_fallback(self):
        """Legacy JSON string in TEXT column must deserialize gracefully."""
        field = EncryptedField(as_json=True)
        legacy_json = '{"key": "value", "num": 7}'
        result = field.process_result_value(legacy_json, dialect=None)
        assert result == {"key": "value", "num": 7}

    def test_different_values_produce_different_tokens(self):
        """Fernet uses random IV — same plaintext ≠ same token."""
        field = EncryptedField()
        t1 = field.process_bind_param("same text", dialect=None)
        t2 = field.process_bind_param("same text", dialect=None)
        assert t1 != t2  # IVs differ
        # But both decrypt to the same value
        assert field.process_result_value(t1, None) == "same text"
        assert field.process_result_value(t2, None) == "same text"


# ══════════════════════════════════════════════════════════════════════════════
# 2. SensitiveFilter — log redaction
# ══════════════════════════════════════════════════════════════════════════════

class TestSensitiveFilter:
    def _filter(self, msg: str) -> str:
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg=msg, args=(), exc_info=None,
        )
        f.filter(record)
        return record.msg

    def test_api_key_redacted(self):
        msg = "Using key " + "sk_live_" + ("A" * 32)
        result = self._filter(msg)
        assert "sk_live_***" in result
        assert ("A" * 32) not in result

    def test_bearer_token_redacted(self):
        msg = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
        result = self._filter(msg)
        assert "Bearer [REDACTED]" in result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_password_in_json_redacted(self):
        msg = '{"email": "user@example.com", "password": "MySecret1"}'
        result = self._filter(msg)
        assert '"password": "***"' in result
        assert "MySecret1" not in result

    def test_hashed_password_redacted(self):
        msg = '{"hashed_password": "$2b$12$XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"}'
        result = self._filter(msg)
        assert "hashed_password" in result
        assert "$2b$12$" not in result

    def test_anthropic_key_redacted(self):
        msg = "ANTHROPIC_API_KEY=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
        result = self._filter(msg)
        assert "sk-ant-***" in result

    def test_refresh_token_truncated(self):
        msg = '{"refresh_token": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"}'
        result = self._filter(msg)
        assert "abcdefgh" in result          # first 8 chars kept
        assert "[REDACTED]" in result
        assert "ijklmnopqrstuvwxyz0123456789ABCDEF" not in result

    def test_safe_content_not_redacted(self):
        msg = "User john@example.com logged in from 192.168.1.1"
        result = self._filter(msg)
        assert result == msg


# ══════════════════════════════════════════════════════════════════════════════
# 3. Security response headers
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-xss-protection"] == "1; mode=block"
    assert "default-src" in r.headers["content-security-policy"]
    assert "strict-origin" in r.headers.get("referrer-policy", "")

@pytest.mark.asyncio
async def test_security_headers_on_error_response(client):
    r = await client.get("/api/v1/agents")   # 401 — no auth
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"

@pytest.mark.asyncio
async def test_hsts_absent_when_https_not_enforced(client):
    """HSTS must NOT appear when ENFORCE_HTTPS is False (development)."""
    r = await client.get("/health")
    assert "strict-transport-security" not in r.headers


# ══════════════════════════════════════════════════════════════════════════════
# 4. HTTPS enforcement middleware
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_https_redirect_when_enforced(client):
    from app.core import config as cfg_module
    original = cfg_module.settings.ENFORCE_HTTPS
    cfg_module.settings.ENFORCE_HTTPS = True
    try:
        r = await client.get(
            "/health",
            headers={"X-Forwarded-Proto": "http"},
            follow_redirects=False,
        )
        assert r.status_code == 301
        assert r.headers["location"].startswith("https://")
    finally:
        cfg_module.settings.ENFORCE_HTTPS = original

@pytest.mark.asyncio
async def test_no_redirect_when_https_proto(client):
    from app.core import config as cfg_module
    original = cfg_module.settings.ENFORCE_HTTPS
    cfg_module.settings.ENFORCE_HTTPS = True
    try:
        r = await client.get(
            "/health",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
        assert r.status_code == 200
    finally:
        cfg_module.settings.ENFORCE_HTTPS = original


# ══════════════════════════════════════════════════════════════════════════════
# 5. JWT token expiry
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_expired_jwt_rejected(client):
    from datetime import timedelta
    from app.core.security import create_access_token

    # Create a token that expired 1 second ago
    expired_token = create_access_token(
        {"user_id": "00000000-0000-0000-0000-000000000099", "email": "x@x.com", "role": "user"},
        expires_delta=timedelta(seconds=-1),
    )
    r = await client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_tampered_jwt_rejected(client):
    tokens = await _register_and_login(client, "tamper@example.com", "Password1")
    good_token = tokens["access_token"]
    # Flip last character
    tampered = good_token[:-1] + ("A" if good_token[-1] != "A" else "B")
    r = await client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_missing_auth_header_rejected(client):
    r = await client.get("/api/v1/agents")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Audit log entries
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_audit_log_written_on_register(client, db):
    await client.post(
        "/auth/register",
        json={"email": "audit_reg@example.com", "password": "Password1"},
    )
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "user.register",
        )
    )
    rows = result.scalars().all()
    assert any(r.resource_type == "user" for r in rows)

@pytest.mark.asyncio
async def test_audit_log_written_on_login(client, db):
    await client.post("/auth/register", json={"email": "audit_log@example.com", "password": "Password1"})
    await client.post("/auth/login", json={"email": "audit_log@example.com", "password": "Password1"})

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.login")
    )
    assert result.scalars().first() is not None

@pytest.mark.asyncio
async def test_audit_log_written_on_failed_login(client, db):
    await client.post("/auth/register", json={"email": "audit_fail@example.com", "password": "Password1"})
    await client.post("/auth/login", json={"email": "audit_fail@example.com", "password": "WrongPass1"})

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.login_fail")
    )
    row = result.scalars().first()
    assert row is not None
    assert row.success is False

@pytest.mark.asyncio
async def test_audit_log_written_on_api_key_create(client, db):
    tokens = await _register_and_login(client, "audit_key@example.com", "Password1")
    access_token = tokens["access_token"]

    await client.post(
        "/api/v1/keys",
        json={"name": "Test Key"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "api_key.create")
    )
    assert result.scalars().first() is not None

@pytest.mark.asyncio
async def test_audit_log_written_on_logout(client, db):
    tokens = await _register_and_login(client, "audit_out@example.com", "Password1")
    await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.logout")
    )
    assert result.scalars().first() is not None


# ══════════════════════════════════════════════════════════════════════════════
# 7. DB SSL config is wired (unit check — no live DB needed)
# ══════════════════════════════════════════════════════════════════════════════

def test_database_ssl_mode_config_readable():
    from app.core.config import settings
    # Default is empty string (disabled in dev)
    assert isinstance(settings.DATABASE_SSL_MODE, str)

def test_encryption_key_config_readable():
    from app.core.config import settings
    assert len(settings.ENCRYPTION_KEY) > 10
