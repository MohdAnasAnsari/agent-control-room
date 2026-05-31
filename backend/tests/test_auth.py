"""
Auth endpoint tests — register, login, refresh, logout, API keys, RBAC.

Uses pytest-asyncio with an in-memory SQLite database so no Postgres is needed.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models.database import Base
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


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _register(client: AsyncClient, email: str = "user@example.com", password: str = "Password1") -> dict:
    r = await client.post("/auth/register", json={"email": email, "password": password})
    return r


async def _login(client: AsyncClient, email: str = "user@example.com", password: str = "Password1") -> dict:
    r = await client.post("/auth/login", json={"email": email, "password": password})
    return r


# ── Register ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client):
    r = await _register(client, "new@example.com", "Secure1pass")
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "new@example.com"
    assert data["role"] == "user"
    assert "id" in data
    assert "hashed_password" not in data

@pytest.mark.asyncio
async def test_register_weak_password_no_uppercase(client):
    r = await client.post("/auth/register", json={"email": "a@b.com", "password": "password1"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"

@pytest.mark.asyncio
async def test_register_weak_password_no_number(client):
    r = await client.post("/auth/register", json={"email": "a@b.com", "password": "Password"})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_register_weak_password_too_short(client):
    r = await client.post("/auth/register", json={"email": "a@b.com", "password": "Ab1"})
    assert r.status_code == 422  # pydantic min_length=8

@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await _register(client, "dup@example.com", "Password1")
    r = await _register(client, "dup@example.com", "Password1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"

@pytest.mark.asyncio
async def test_register_invalid_email(client):
    r = await client.post("/auth/register", json={"email": "not-an-email", "password": "Password1"})
    assert r.status_code == 422


# ── Login ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client):
    await _register(client, "login@example.com", "Password1")
    r = await _login(client, "login@example.com", "Password1")
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "login@example.com"

@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await _register(client, "wrongpw@example.com", "Password1")
    r = await _login(client, "wrongpw@example.com", "WrongPass1")
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Invalid email or password"

@pytest.mark.asyncio
async def test_login_unknown_email(client):
    r = await _login(client, "ghost@example.com", "Password1")
    assert r.status_code == 401
    # Must not reveal whether email exists
    assert r.json()["error"]["message"] == "Invalid email or password"


# ── Refresh ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token_success(client):
    await _register(client, "refresh@example.com", "Password1")
    login_r = await _login(client, "refresh@example.com", "Password1")
    refresh_token = login_r.json()["refresh_token"]

    r = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert "access_token" in r.json()

@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    r = await client.post("/auth/refresh", json={"refresh_token": "invalid_garbage"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_refresh_blacklisted_token(client):
    await _register(client, "blacklist@example.com", "Password1")
    login_r = await _login(client, "blacklist@example.com", "Password1")
    refresh_token = login_r.json()["refresh_token"]

    # logout — blacklists the refresh token
    await client.post("/auth/logout", json={"refresh_token": refresh_token})

    r = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401


# ── Logout ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_success(client):
    await _register(client, "logout@example.com", "Password1")
    login_r = await _login(client, "logout@example.com", "Password1")
    refresh_token = login_r.json()["refresh_token"]

    r = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert r.json()["success"] is True

@pytest.mark.asyncio
async def test_logout_no_token_still_succeeds(client):
    r = await client.post("/auth/logout")
    assert r.status_code == 200


# ── Protected routes ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protected_route_no_token(client):
    r = await client.get("/api/v1/agents")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_protected_route_with_valid_token(client):
    await _register(client, "protected@example.com", "Password1")
    login_r = await _login(client, "protected@example.com", "Password1")
    access_token = login_r.json()["access_token"]

    r = await client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_protected_route_with_invalid_token(client):
    r = await client.get(
        "/api/v1/agents",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert r.status_code == 401


# ── API key authentication ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_key_create_and_use(client):
    await _register(client, "apikey@example.com", "Password1")
    login_r = await _login(client, "apikey@example.com", "Password1")
    access_token = login_r.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    # Create API key
    r = await client.post("/api/v1/keys", json={"name": "My Key"}, headers=auth_headers)
    assert r.status_code == 201
    key_data = r.json()
    assert key_data["key"].startswith("sk_live_")
    assert len(key_data["key"]) == 8 + 32  # "sk_live_" + 32 chars
    assert "key" in key_data  # only returned on creation

    raw_key = key_data["key"]

    # Use API key to access a protected route
    r2 = await client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r2.status_code == 200

@pytest.mark.asyncio
async def test_api_key_list(client):
    await _register(client, "keylist@example.com", "Password1")
    login_r = await _login(client, "keylist@example.com", "Password1")
    access_token = login_r.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    await client.post("/api/v1/keys", json={"name": "K1"}, headers=auth_headers)
    await client.post("/api/v1/keys", json={"name": "K2"}, headers=auth_headers)

    r = await client.get("/api/v1/keys", headers=auth_headers)
    assert r.status_code == 200
    keys = r.json()
    assert len(keys) == 2
    # raw key must NOT be returned in list
    for k in keys:
        assert "key" not in k

@pytest.mark.asyncio
async def test_api_key_revoke(client):
    await _register(client, "revoke@example.com", "Password1")
    login_r = await _login(client, "revoke@example.com", "Password1")
    access_token = login_r.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    create_r = await client.post("/api/v1/keys", json={"name": "Revoke Me"}, headers=auth_headers)
    key_id = create_r.json()["id"]
    raw_key = create_r.json()["key"]

    # Revoke it
    r = await client.delete(f"/api/v1/keys/{key_id}", headers=auth_headers)
    assert r.status_code == 204

    # Using the revoked key should fail
    r2 = await client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r2.status_code == 401


# ── RBAC ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rbac_admin_endpoint_blocked_for_user(client):
    """Example: admin-only endpoint returns 403 for a regular user."""
    await _register(client, "norole@example.com", "Password1")
    login_r = await _login(client, "norole@example.com", "Password1")
    access_token = login_r.json()["access_token"]

    # /api/v1/admin/users is the example from the spec — not implemented yet,
    # but we can verify the require_role dependency raises 403 for a non-admin.
    # We test via a direct call to require_role to confirm the logic.
    from app.core.deps import require_role
    from app.models.database import User
    from fastapi import HTTPException
    import pytest

    mock_user = User(email="u@u.com", hashed_password="x", role="user")

    checker = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user=mock_user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "FORBIDDEN"
