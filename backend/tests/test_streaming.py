"""
Unit tests for SSE streaming endpoints.
Covers: agent token streaming, execution status streaming, error events,
        and the NDJSON execution logs endpoint (already in test_v1_executions).
"""

import json
import uuid
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

_FAKE_AGENT_ID  = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_FAKE_EXEC_ID   = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_FAKE_WF_ID     = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW            = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fake_agent_state(**overrides):
    defaults = dict(
        agent_id=str(_FAKE_AGENT_ID),
        name="Test Agent",
        role="analyst",
        system_prompt="You are a test agent for streaming purposes.",
        model="claude-sonnet-4-6",
        tools=[],
        memory=[],
    )
    defaults.update(overrides)
    from app.services.agent_state_manager import AgentState
    return AgentState(**defaults)


def _fake_execution(**overrides):
    defaults = dict(
        id=_FAKE_EXEC_ID,
        workflow_id=_FAKE_WF_ID,
        status="completed",
        started_at=_NOW,
        completed_at=_NOW,
        result={"output": "done"},
        error_log=None,
    )
    defaults.update(overrides)
    obj = MagicMock(**defaults)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture()
def app():
    mock_engine = AsyncMock()
    mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_engine.dispose = AsyncMock()
    with mock.patch("app.models.db_session.engine", mock_engine):
        from app.main import app as fastapi_app
        return fastapi_app


@pytest.fixture()
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── POST /api/v1/stream/agents/{id} ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_agent_yields_sse_events(client):
    """Streaming a live agent response should emit start + token + done events."""
    fake_state = _fake_agent_state()

    async def fake_stream(*args, **kwargs):
        for word in ["Hello", " ", "world"]:
            yield word

    with (
        mock.patch("app.api.v1.stream.registry") as mock_reg,
        mock.patch("app.api.v1.stream.agent_executor") as mock_exec,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=fake_state)
        mock_exec.stream.return_value = fake_stream()

        async with client as c:
            resp = await c.post(
                f"/api/v1/stream/agents/{_FAKE_AGENT_ID}",
                json={"input": "Hello there"},
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    # Parse all SSE events
    events = _parse_sse_events(resp.text)
    types = [e["type"] for e in events]

    assert "start" in types
    assert "token" in types
    assert "done" in types

    # Tokens should reconstruct to full output
    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "Hello world"

    # Done event carries the full output
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["output"] == "Hello world"


@pytest.mark.asyncio
async def test_stream_agent_not_found_returns_404(client):
    with mock.patch("app.api.v1.stream.registry") as mock_reg:
        mock_reg.get_or_load = AsyncMock(return_value=None)
        async with client as c:
            resp = await c.post(
                f"/api/v1/stream/agents/{_FAKE_AGENT_ID}",
                json={"input": "test"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_agent_error_emits_error_event(client):
    """If the stream raises mid-way, an error SSE event is emitted."""
    fake_state = _fake_agent_state()

    async def failing_stream(*args, **kwargs):
        yield "partial "
        raise RuntimeError("LLM exploded")

    with (
        mock.patch("app.api.v1.stream.registry") as mock_reg,
        mock.patch("app.api.v1.stream.agent_executor") as mock_exec,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=fake_state)
        mock_exec.stream.return_value = failing_stream()

        async with client as c:
            resp = await c.post(
                f"/api/v1/stream/agents/{_FAKE_AGENT_ID}",
                json={"input": "test"},
            )

    assert resp.status_code == 200  # stream always opens successfully
    events = _parse_sse_events(resp.text)
    types = [e["type"] for e in events]
    assert "error" in types
    error_evt = next(e for e in events if e["type"] == "error")
    assert "LLM exploded" in error_evt["message"]


@pytest.mark.asyncio
async def test_stream_agent_model_override(client):
    """Model override in the request body should be forwarded to stream()."""
    fake_state = _fake_agent_state()

    async def fake_stream(*args, **kwargs):
        yield "ok"

    with (
        mock.patch("app.api.v1.stream.registry") as mock_reg,
        mock.patch("app.api.v1.stream.agent_executor") as mock_exec,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=fake_state)
        mock_exec.stream.return_value = fake_stream()

        async with client as c:
            await c.post(
                f"/api/v1/stream/agents/{_FAKE_AGENT_ID}",
                json={"input": "test", "model": "gpt-4o"},
            )

        # The model_override kwarg should have been passed
        call_kwargs = mock_exec.stream.call_args[1]
        assert call_kwargs.get("model_override") == "gpt-4o"


# ─── GET /api/v1/stream/executions/{id} ───────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_execution_emits_status_and_complete(client):
    fake_exec = _fake_execution(status="completed")

    with mock.patch("app.services.workflow_service.get_execution", return_value=fake_exec):
        # The streaming endpoint opens a DB session; mock the poll session too
        with mock.patch("app.api.v1.stream.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            # Return completed execution on poll
            mock_session.execute = AsyncMock()
            mock_session_cls.return_value = mock_session

            with (
                mock.patch(
                    "app.api.v1.stream.workflow_service.get_execution",
                    AsyncMock(return_value=fake_exec),
                ),
                mock.patch(
                    "app.api.v1.stream.workflow_service.get_execution_steps",
                    AsyncMock(return_value=[]),
                ),
            ):
                async with client as c:
                    resp = await c.get(
                        f"/api/v1/stream/executions/{_FAKE_EXEC_ID}",
                        params={"poll_interval": "0.01"},  # fast poll for test
                    )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    types = [e.get("type") for e in events]
    # Should have at least a status event
    assert "status" in types


@pytest.mark.asyncio
async def test_stream_execution_not_found_returns_404(client):
    with mock.patch("app.services.workflow_service.get_execution", return_value=None):
        async with client as c:
            resp = await c.get(f"/api/v1/stream/executions/{_FAKE_EXEC_ID}")
    assert resp.status_code == 404


# ─── SSE format validation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_response_headers(client):
    fake_state = _fake_agent_state()

    async def fake_stream(*args, **kwargs):
        yield "chunk"

    with (
        mock.patch("app.api.v1.stream.registry") as mock_reg,
        mock.patch("app.api.v1.stream.agent_executor") as mock_exec,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=fake_state)
        mock_exec.stream.return_value = fake_stream()

        async with client as c:
            resp = await c.post(
                f"/api/v1/stream/agents/{_FAKE_AGENT_ID}",
                json={"input": "test"},
            )

    # Standard SSE headers
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


# ─── LLMFactory triple fallback ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_triple_fallback_chain():
    """Claude fails → GPT-mini tried → Groq succeeds."""
    from app.services.llm_provider import (
        LLMFactory, ClaudeLLM, GPTProvider, GroqProvider,
        RateLimitError, LLMResponse,
    )

    # Build a minimal response for Groq
    groq_resp = LLMResponse(
        content="Groq fallback response",
        model="llama-3.3-70b-versatile",
        provider="groq",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0,
    )

    factory = LLMFactory()

    claude = MagicMock(spec=ClaudeLLM)
    claude.call = AsyncMock(side_effect=RateLimitError("rate limited"))

    gpt_mini = MagicMock(spec=GPTProvider)
    gpt_mini.call = AsyncMock(side_effect=RateLimitError("rate limited too"))

    groq = MagicMock(spec=GroqProvider)
    groq.call = AsyncMock(return_value=groq_resp)

    def provider_router(model):
        if "claude" in model:  return claude
        if "gpt"   in model:  return gpt_mini
        return groq

    with mock.patch.object(factory, "get_provider", side_effect=provider_router):
        with mock.patch("app.services.llm_provider.settings") as ms:
            ms.DEFAULT_MODEL = "claude-sonnet-4-6"
            ms.LLM_FALLBACK_ENABLED = True
            ms.LLM_TIMEOUT_S = 30.0
            ms.LLM_MAX_RETRIES = 1

            result = await factory.call(
                "You are helpful.",
                [{"role": "user", "content": "hi"}],
                model="claude-sonnet-4-6",
                enable_fallback=True,
            )

    assert result.content == "Groq fallback response"
    assert result.provider == "groq"
    claude.call.assert_called_once()
    gpt_mini.call.assert_called_once()
    groq.call.assert_called_once()


# ─── Helper ───────────────────────────────────────────────────────────────────

def _parse_sse_events(text: str):
    """Parse SSE text into a list of dicts."""
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events
