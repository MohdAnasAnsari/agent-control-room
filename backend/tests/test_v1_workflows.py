"""
Unit tests for /api/v1/workflows endpoints.
"""

import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient

_FAKE_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_FAKE_WF_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_FAKE_EXEC_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_SIMPLE_DAG = {
    "nodes": [
        {"id": "step_a", "type": "agent", "agent_id": "some-uuid", "depends_on": []},
    ]
}


def _fake_workflow(**overrides):
    defaults = dict(
        id=_FAKE_WF_ID,
        user_id=_FAKE_USER_ID,
        name="Test Workflow",
        dag_config=_SIMPLE_DAG,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    obj = mock.MagicMock(**defaults)
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


# ─── POST /api/v1/workflows ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_workflow_with_nodes(client):
    fake = _fake_workflow()
    with mock.patch("app.services.workflow_service.create_workflow", return_value=fake):
        async with client as c:
            resp = await c.post("/api/v1/workflows", json={
                "name": "My Pipeline",
                "nodes": [
                    {"id": "step_a", "type": "agent", "agent_id": "some-uuid"},
                ],
            })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Test Workflow"


@pytest.mark.asyncio
async def test_create_workflow_cyclic_dag_rejected(client):
    async with client as c:
        resp = await c.post("/api/v1/workflows", json={
            "name": "Cyclic",
            "nodes": [
                {"id": "a", "type": "agent", "agent_id": "x", "depends_on": ["b"]},
                {"id": "b", "type": "agent", "agent_id": "y", "depends_on": ["a"]},
            ],
        })
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "INVALID_WORKFLOW"


@pytest.mark.asyncio
async def test_create_workflow_backward_compat_dag_config(client):
    fake = _fake_workflow()
    with mock.patch("app.services.workflow_service.create_workflow", return_value=fake):
        async with client as c:
            resp = await c.post("/api/v1/workflows", json={
                "name": "Legacy",
                "dag_config": _SIMPLE_DAG,
            })
    assert resp.status_code == 201


# ─── GET /api/v1/workflows ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_workflows_paginated(client):
    fakes = [_fake_workflow(id=uuid.uuid4()) for _ in range(3)]
    with mock.patch("app.services.workflow_service.list_workflows", return_value=(10, fakes)):
        async with client as c:
            resp = await c.get("/api/v1/workflows?skip=0&limit=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 10
    assert body["has_more"] is True
    assert resp.headers["X-Total-Count"] == "10"


@pytest.mark.asyncio
async def test_list_workflows_is_active_filter(client):
    with mock.patch(
        "app.services.workflow_service.list_workflows", return_value=(0, [])
    ) as m:
        async with client as c:
            await c.get("/api/v1/workflows?is_active=true")
        m.assert_called_once()
        _, kwargs = m.call_args
        assert kwargs.get("is_active") is True


# ─── GET /api/v1/workflows/{id} ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_workflow_found(client):
    fake = _fake_workflow()
    with mock.patch("app.services.workflow_service.get_workflow", return_value=fake):
        async with client as c:
            resp = await c.get(f"/api/v1/workflows/{_FAKE_WF_ID}")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_get_workflow_not_found(client):
    with mock.patch("app.services.workflow_service.get_workflow", return_value=None):
        async with client as c:
            resp = await c.get(f"/api/v1/workflows/{_FAKE_WF_ID}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# ─── PATCH /api/v1/workflows/{id} ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_workflow_deactivate(client):
    updated = _fake_workflow(is_active=False)
    with mock.patch("app.services.workflow_service.update_workflow", return_value=updated):
        async with client as c:
            resp = await c.patch(
                f"/api/v1/workflows/{_FAKE_WF_ID}",
                json={"is_active": False},
            )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_patch_workflow_cyclic_dag_rejected(client):
    async with client as c:
        resp = await c.patch(
            f"/api/v1/workflows/{_FAKE_WF_ID}",
            json={
                "nodes": [
                    {"id": "x", "depends_on": ["y"], "type": "agent", "agent_id": "u1"},
                    {"id": "y", "depends_on": ["x"], "type": "agent", "agent_id": "u2"},
                ]
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_WORKFLOW"


# ─── DELETE /api/v1/workflows/{id} ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_workflow_success(client):
    with mock.patch("app.services.workflow_service.delete_workflow", return_value=True):
        async with client as c:
            resp = await c.delete(f"/api/v1/workflows/{_FAKE_WF_ID}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_workflow_not_found(client):
    with mock.patch("app.services.workflow_service.delete_workflow", return_value=False):
        async with client as c:
            resp = await c.delete(f"/api/v1/workflows/{_FAKE_WF_ID}")
    assert resp.status_code == 404


# ─── POST /api/v1/workflows/{id}/execute ─────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_workflow_async(client):
    fake_wf = _fake_workflow()
    fake_run = mock.MagicMock()
    fake_run.execution_id = str(_FAKE_EXEC_ID)
    fake_run.status = "running"
    fake_run.to_dict.return_value = {}

    with (
        mock.patch("app.services.workflow_service.get_workflow", return_value=fake_wf),
        mock.patch(
            "app.api.v1.workflows._get_orchestrator",
            return_value=mock.MagicMock(
                execute_workflow=mock.AsyncMock(return_value=fake_run)
            ),
        ),
    ):
        async with client as c:
            resp = await c.post(
                f"/api/v1/workflows/{_FAKE_WF_ID}/execute",
                json={"input_data": {"query": "test"}, "run_async": True},
            )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "execution_id" in body


@pytest.mark.asyncio
async def test_execute_inactive_workflow(client):
    fake_wf = _fake_workflow(is_active=False)
    with mock.patch("app.services.workflow_service.get_workflow", return_value=fake_wf):
        async with client as c:
            resp = await c.post(
                f"/api/v1/workflows/{_FAKE_WF_ID}/execute",
                json={"input_data": {}, "run_async": True},
            )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "WORKFLOW_INACTIVE"


# ─── GET /api/v1/models ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_models(client):
    async with client as c:
        resp = await c.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "production" in body
    assert "testing" in body
    assert "claude-sonnet-4-6" in body["production"]
