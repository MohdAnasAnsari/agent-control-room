"""
Unit tests for agent_executor.py

Covers: full execution flow, tool calling, follow-up LLM call,
        memory updates, context window pruning, error handling,
        and the streaming interface.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_executor import AgentExecutor
from app.services.agent_state_manager import AgentState, AgentStatus
from app.services.llm_provider import LLMResponse, ToolCall


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _make_state(**overrides) -> AgentState:
    defaults = dict(
        agent_id="aaaa-0001",
        name="Test Agent",
        role="analyst",
        system_prompt="You are a helpful test assistant that handles queries professionally.",
        model="claude-sonnet-4-6",
        tools=[],
        memory=[],
    )
    defaults.update(overrides)
    return AgentState(**defaults)


def _make_llm_response(content="Analysis complete.", tool_calls=None) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=50,
        output_tokens=25,
        tool_calls=tool_calls or [],
        finish_reason="end_turn",
        cost_usd=0.000225,
    )


def _input_data(text="Analyze this data") -> Dict[str, Any]:
    return {"input": text, "workflow_input": {}}


# ─── 1. Basic execution (no tools) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_basic_success():
    executor = AgentExecutor()
    state = _make_state()
    llm_resp = _make_llm_response("Analysis complete.")

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_reg.mark_critical = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(return_value=llm_resp)

        result = await executor.execute(
            "aaaa-0001", _input_data(), {"current_node_id": "step_a"}
        )

    assert result["output"] == "Analysis complete."
    assert result["agent_id"] == "aaaa-0001"
    assert result["agent_name"] == "Test Agent"
    assert result["model"] == "claude-sonnet-4-6"
    assert result["tokens"]["input"] == 100  # both calls summed
    assert result["cost_usd"] == pytest.approx(0.00045)
    assert isinstance(result["duration_ms"], int)


@pytest.mark.asyncio
async def test_execute_sets_running_then_idle():
    executor = AgentExecutor()
    state = _make_state()
    statuses = []

    original_set_status = state.set_status
    def recording_set_status(s):
        statuses.append(s)
        original_set_status(s)

    state.set_status = recording_set_status

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(return_value=_make_llm_response())

        await executor.execute("aaaa-0001", _input_data(), {})

    assert AgentStatus.RUNNING in statuses
    assert AgentStatus.IDLE in statuses


@pytest.mark.asyncio
async def test_execute_updates_memory():
    executor = AgentExecutor()
    state = _make_state()

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(return_value=_make_llm_response("Done."))

        await executor.execute("aaaa-0001", _input_data("My question"), {})

    # Memory should have user + assistant entries
    roles = [m["role"] for m in state.memory]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_execute_agent_not_found_raises():
    executor = AgentExecutor()

    with patch("app.services.agent_executor._registry") as mock_reg:
        mock_reg.get_or_load = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await executor.execute("missing-id", _input_data(), {})


# ─── 2. Tool calling flow ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_with_tool_calls_triggers_followup():
    executor = AgentExecutor()
    state = _make_state(tools=["web_search"])

    tool_call = ToolCall(id="tc1", name="web_search", arguments={"query": "latest AI"})
    first_resp  = _make_llm_response("", tool_calls=[tool_call])
    second_resp = _make_llm_response("Here is the summary: ...")

    tool_result = {"tool_call_id": "tc1", "tool": "web_search", "result": {"results": []}}

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
        patch("app.services.agent_executor.execute_tools_parallel", AsyncMock(return_value=[tool_result])),
        patch("app.services.agent_executor.get_tool_definitions", return_value=[]),
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        # First call returns tool_calls; second returns final text
        mock_factory.call = AsyncMock(side_effect=[first_resp, second_resp])

        result = await executor.execute("aaaa-0001", _input_data(), {})

    assert result["output"] == "Here is the summary: ..."
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "web_search"
    assert mock_factory.call.call_count == 2  # first + follow-up


@pytest.mark.asyncio
async def test_execute_no_tools_single_llm_call():
    executor = AgentExecutor()
    state = _make_state(tools=[])

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(return_value=_make_llm_response())

        await executor.execute("aaaa-0001", _input_data(), {})

    assert mock_factory.call.call_count == 1


# ─── 3. Tool result formatting ────────────────────────────────────────────────

def test_format_tool_results_claude_format():
    executor = AgentExecutor()
    calls   = [ToolCall(id="t1", name="web_search", arguments={})]
    results = [{"tool_call_id": "t1", "result": {"data": 123}}]

    msgs = executor._format_tool_results(calls, results, "claude-sonnet-4-6")
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    block = msg["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "t1"


def test_format_tool_results_openai_format():
    executor = AgentExecutor()
    calls   = [ToolCall(id="t2", name="file_read", arguments={})]
    results = [{"tool_call_id": "t2", "result": {"content": "hello"}}]

    msgs = executor._format_tool_results(calls, results, "gpt-4o")
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "t2"


def test_format_tool_results_groq_format():
    executor = AgentExecutor()
    calls   = [ToolCall(id="t3", name="database_query", arguments={})]
    results = [{"tool_call_id": "t3", "result": {"rows": []}}]

    msgs = executor._format_tool_results(calls, results, "llama-3.3-70b-versatile")
    assert msgs[0]["role"] == "tool"


# ─── 4. _extract_user_message ────────────────────────────────────────────────

def test_extract_user_message_from_input_str():
    executor = AgentExecutor()
    msg = executor._extract_user_message({"input": "Hello world"})
    assert msg == "Hello world"


def test_extract_user_message_from_input_dict():
    executor = AgentExecutor()
    msg = executor._extract_user_message({"input": {"query": "What is AI?"}})
    assert msg == "What is AI?"


def test_extract_user_message_from_workflow_input():
    executor = AgentExecutor()
    msg = executor._extract_user_message({"workflow_input": {"query": "Analyze data"}})
    assert msg == "Analyze data"


def test_extract_user_message_fallback():
    executor = AgentExecutor()
    msg = executor._extract_user_message({"dep_outputs": {"node_a": "some output"}})
    assert isinstance(msg, str) and len(msg) > 0


# ─── 5. Context window pruning ────────────────────────────────────────────────

def test_prepare_history_prunes_when_over_budget():
    executor = AgentExecutor()
    state = _make_state(
        model="llama2-70b-4096",  # tiny 4096 token window
        memory=[
            {"role": "user",      "content": "x" * 200, "timestamp": "..."},
            {"role": "assistant", "content": "y" * 200, "timestamp": "..."},
            {"role": "user",      "content": "z" * 200, "timestamp": "..."},
            {"role": "assistant", "content": "w" * 200, "timestamp": "..."},
        ] * 10,  # 80 messages → definitely over budget
    )

    mock_provider = MagicMock()
    mock_provider.count_tokens = lambda t: len(t)  # 1 char = 1 token

    with patch("app.services.agent_executor.llm_factory") as mock_factory:
        mock_factory.get_provider.return_value = mock_provider
        history = executor._prepare_history(state, "llama2-70b-4096", "short next message")

    # Should have evicted messages; history must be shorter than full memory
    assert len(history) < len(state.memory)


def test_prepare_history_keeps_recent_messages_first():
    executor = AgentExecutor()
    state = _make_state(
        memory=[
            {"role": "user",      "content": "old message 1", "timestamp": "..."},
            {"role": "assistant", "content": "old reply 1",   "timestamp": "..."},
            {"role": "user",      "content": "recent msg",    "timestamp": "..."},
            {"role": "assistant", "content": "recent reply",  "timestamp": "..."},
        ]
    )

    mock_provider = MagicMock()
    mock_provider.count_tokens = lambda t: 1  # trivial tokens

    with patch("app.services.agent_executor.llm_factory") as mock_factory:
        mock_factory.get_provider.return_value = mock_provider
        history = executor._prepare_history(state, "claude-sonnet-4-6", "next")

    # All messages fit; order preserved
    assert history[-1]["content"] == "recent reply"


def test_prepare_history_strips_timestamps():
    executor = AgentExecutor()
    state = _make_state(
        memory=[
            {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00Z"},
        ]
    )

    mock_provider = MagicMock()
    mock_provider.count_tokens = lambda t: 1

    with patch("app.services.agent_executor.llm_factory") as mock_factory:
        mock_factory.get_provider.return_value = mock_provider
        history = executor._prepare_history(state, "claude-sonnet-4-6", "test")

    assert "timestamp" not in history[0]


# ─── 6. Error handling ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_on_llm_error_sets_agent_error_status():
    executor = AgentExecutor()
    state = _make_state()

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_critical = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(side_effect=RuntimeError("API is down"))

        with pytest.raises(RuntimeError, match="API is down"):
            await executor.execute("aaaa-0001", _input_data(), {})

    assert state.status == AgentStatus.ERROR
    mock_reg.mark_critical.assert_called_once_with("aaaa-0001")


# ─── 7. Streaming ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_yields_chunks():
    executor = AgentExecutor()
    state = _make_state()

    async def fake_chunks(*args, **kwargs):
        for chunk in ["Hello", " ", "world", "!"]:
            yield chunk

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_factory.stream.return_value = fake_chunks()

        chunks = []
        async for chunk in executor.stream("aaaa-0001", "Hi"):
            chunks.append(chunk)

    assert "".join(chunks) == "Hello world!"


@pytest.mark.asyncio
async def test_stream_agent_not_found_raises():
    executor = AgentExecutor()
    with patch("app.services.agent_executor._registry") as mock_reg:
        mock_reg.get_or_load = AsyncMock(return_value=None)
        with pytest.raises(ValueError):
            async for _ in executor.stream("missing", "Hi"):
                pass


# ─── 8. increment_execution called once per run ───────────────────────────────

@pytest.mark.asyncio
async def test_execute_increments_execution_count():
    executor = AgentExecutor()
    state = _make_state()
    initial_count = state.execution_count

    with (
        patch("app.services.agent_executor._registry") as mock_reg,
        patch("app.services.agent_executor.llm_factory") as mock_factory,
    ):
        mock_reg.get_or_load = AsyncMock(return_value=state)
        mock_reg.mark_dirty = AsyncMock()
        mock_factory.get_provider.return_value = MagicMock(
            count_tokens=lambda t: len(t) // 4
        )
        mock_factory.call = AsyncMock(return_value=_make_llm_response())

        await executor.execute("aaaa-0001", _input_data(), {})

    assert state.execution_count == initial_count + 1
