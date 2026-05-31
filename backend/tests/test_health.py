"""
Smoke tests — verify the app starts and /health responds.
Run with:  pytest tests/ -v
Requires: pip install -r requirements.txt  (no live DB needed for health check)
"""
import pytest
from httpx import ASGITransport, AsyncClient

# Patch DB engine so tests don't need a real Postgres
import unittest.mock as mock

# Suppress startup DB create_all by mocking the engine
mock_engine = mock.AsyncMock()
mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock.AsyncMock())
mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
mock_engine.dispose = mock.AsyncMock()


@pytest.fixture()
def app():
    with mock.patch("app.models.db_session.engine", mock_engine):
        from app.main import app as fastapi_app
        return fastapi_app


@pytest.mark.asyncio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_docs_available(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unknown_route_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/not-a-real-route")
    assert response.status_code == 404
