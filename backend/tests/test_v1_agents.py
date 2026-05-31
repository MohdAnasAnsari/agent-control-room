"""
Unit tests for /api/v1/agents endpoints.
No real database — all DB calls are mocked.
"""

import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient

# ─── Shared fixtures ──────────────────────────────────────────────────────────

_FAKE_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_FAKE_AGENT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _fake_agent(**overrides):
    defaults = dict(
        id=_FAKE_AGENT_ID,
        user_id=_FAKE_USER_ID,
        name="Test Agent",
        role="analyst",
        system_prompt="You are a test agent for unit testing purposes here.",
        model="claude-sonnet-4-6",
        status="active",
        tools=[],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    obj = mock.MagicMock(**defaults)
    obj.__iter__ = mock.Mock(return_value=iter([]))
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture()
def app():
    mock_engine = mock.AsyncMock()
    mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock.AsyncMock())
    mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
    mock_engine.dispose = mock.AsyncMock()
    with mock.patch("app.models.db_session.engine", mock_engine):
        from app.main import app as fastapi_app
        return fastapi_app


@pytest.fixture()
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── POST /api/v1/agents ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_agent_success(client):
    fake = _fake_agent()
    with (
        mock.patch("app.services.agent_service.create_agent", return_value=fake),
        mock.patch("app.models.db_session.get_db", return_value=mock.AsyncMock()),
    ):
        async with client as c:
            resp = await c.post("/api/v1/agents", json={
                "name": "My Agent",
                "role": "analyst",
                "system_prompt": "You are an expert analyst for data processing tasks.",
                "model": "claude-sonnet-4-6",
                "tools": ["web_search"],
            })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Test Agent"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_agent_name_too_short(client):
    async with client as c:
        resp = await c.post("/api/v1/agents", json={
            "name": "AB",
            "role": "analyst",
            "system_prompt": "You are an expert analyst for data processing tasks.",
            "model": "claude-sonnet-4-6",
        })
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_agent_prompt_too_short(client):
    async with client as c:
        resp = await c.post("/api/v1/agents", json={
            "name": "Valid Name",
            "role": "analyst",
            "system_prompt": "Too short",
            "model": "claude-sonnet-4-6",
        })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_agent_invalid_model(client):
    async with client as c:
        resp = await c.post("/api/v1/agents", json={
            "name": "Valid Name",
            "role": "analyst",
            "system_prompt": "You are an expert analyst for data processing tasks.",
            "model": "nonexistent-model-xyz",
        })
    assert resp.status_code == 400


# ─── GET /api/v1/agents ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_agents_default_pagination(client):
    fake = _fake_agent()
    with mock.patch("app.services.agent_service.list_agents", return_value=(1, [fake])):
        async with client as c:
            resp = await c.get("/api/v1/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["has_more"] is False
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_list_agents_pagination_has_more(client):
    fakes = [_fake_agent(id=uuid.uuid4()) for _ in range(5)]
    with mock.patch("app.services.agent_service.list_agents", return_value=(20, fakes)):
        async with client as c:
            resp = await c.get("/api/v1/agents?skip=0&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 20
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_list_agents_limit_max_100(client):
    with mock.patch("app.services.agent_service.list_agents", return_value=(0, [])):
        async with client as c:
            resp = await c.get("/api/v1/agents?limit=200")
    assert resp.status_code == 400  # query param validation


# ─── GET /api/v1/agents/{id} ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_agent_found(client):
    fake = _fake_agent()
    from app.models.schemas import AgentStats
    fake_stats = AgentStats(total_executions=5, successful_executions=4, failed_executions=1)
    with (
        mock.patch("app.services.agent_service.get_agent", return_value=fake),
        mock.patch("app.services.agent_service.get_agent_stats", return_value=fake_stats),
    ):
        async with client as c:
            resp = await c.get(f"/api/v1/agents/{_FAKE_AGENT_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"]["total_executions"] == 5
    assert body["stats"]["successful_executions"] == 4


@pytest.mark.asyncio
async def test_get_agent_not_found(client):
    with mock.patch("app.services.agent_service.get_agent", return_value=None):
        async with client as c:
            resp = await c.get(f"/api/v1/agents/{_FAKE_AGENT_ID}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"


# ─── PATCH /api/v1/agents/{id} ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_agent_partial(client):
    updated = _fake_agent(name="Updated Name")
    with mock.patch("app.services.agent_service.update_agent", return_value=updated):
        async with client as c:
            resp = await c.patch(
                f"/api/v1/agents/{_FAKE_AGENT_ID}",
                json={"name": "Updated Name"},
            )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_patch_agent_not_found(client):
    with mock.patch("app.services.agent_service.update_agent", return_value=None):
        async with client as c:
            resp = await c.patch(
                f"/api/v1/agents/{_FAKE_AGENT_ID}",
                json={"name": "New Name OK"},
            )
    assert resp.status_code == 404


# ─── DELETE /api/v1/agents/{id} ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_agent_success(client):
    with mock.patch("app.services.agent_service.delete_agent", return_value=True):
        async with client as c:
            resp = await c.delete(f"/api/v1/agents/{_FAKE_AGENT_ID}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_agent_not_found(client):
    with mock.patch("app.services.agent_service.delete_agent", return_value=False):
        async with client as c:
            resp = await c.delete(f"/api/v1/agents/{_FAKE_AGENT_ID}")
    assert resp.status_code == 404
