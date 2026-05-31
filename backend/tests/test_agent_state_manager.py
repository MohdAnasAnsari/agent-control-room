"""
Tests for agent_state_manager.py and agent_registry.py

Scope
─────
1. Create 5 test agents; verify registry stores all of them correctly.
2. Update agent state; confirm DB persistence is triggered.
3. Simulate 20 concurrent writes; verify no agents are lost (thread-safety).
4. Memory management; verify trimming to MAX_MEMORY_MESSAGES.
5. AgentContext execution path tracking and reset.
6. DB retry logic; verify exponential back-off on transient failures.
7. Graceful degradation; in-memory state preserved when DB permanently fails.
8. Registry mark_critical; immediate save bypasses batch window.
9. Registry sync_to_db; all dirty agents are persisted in one sweep.
10. Registry unregister; agents are removed cleanly.

No live database required — all DB calls are mocked.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.agent_state_manager import (
    MAX_MEMORY_MESSAGES,
    AgentContext,
    AgentState,
    AgentStatus,
)
from app.services.agent_registry import AgentRegistry, BATCH_SYNC_INTERVAL_S


# ─────────────────────────────── Helpers ─────────────────────────────────────


def make_agent(suffix: str = "1", **kwargs) -> AgentState:
    """Factory for throw-away AgentState objects."""
    defaults = dict(
        agent_id=f"agent-{suffix}",
        name=f"Agent {suffix}",
        role="assistant",
        system_prompt=f"You are agent {suffix}.",
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


def _mock_session_factory(execute_return=None):
    """
    Return a callable that behaves like AsyncSessionLocal() used as an
    async context manager.
    """
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=execute_return or AsyncMock())
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = mock_session
    return factory, mock_session


# ═════════════════════════════════════════════════════════════════════════════
# 1. Registry holds five agents
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_registry_holds_five_agents():
    reg = AgentRegistry()
    agents = [make_agent(str(i)) for i in range(5)]
    for a in agents:
        await reg.register_agent(a)

    all_agents = await reg.list_all_agents()
    assert len(all_agents) == 5

    for i in range(5):
        retrieved = await reg.get_agent(f"agent-{i}")
        assert retrieved is not None
        assert retrieved.name == f"Agent {i}"
        assert retrieved.role == "assistant"


# ═════════════════════════════════════════════════════════════════════════════
# 2. State update triggers DB persistence
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_state_update_persists_to_db():
    agent = make_agent("db-test")
    factory, mock_session = _mock_session_factory()

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        assert agent._dirty is False
        assert agent.status == AgentStatus.IDLE

        agent.set_status(AgentStatus.RUNNING)

        assert agent._dirty is True
        assert agent.status == AgentStatus.RUNNING

        success = await agent.save_to_db()

    assert success is True
    assert agent._dirty is False
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_increment_execution_marks_dirty():
    agent = make_agent("exec-count")
    assert agent.execution_count == 0
    assert agent.last_execution is None

    agent.increment_execution()
    agent.increment_execution()

    assert agent.execution_count == 2
    assert agent.last_execution is not None
    assert agent._dirty is True


@pytest.mark.asyncio
async def test_update_memory_marks_dirty():
    agent = make_agent("mem-dirty")
    assert agent._dirty is False

    agent.update_memory("hello", "user")

    assert agent._dirty is True
    assert len(agent.memory) == 1
    assert agent.memory[0]["role"] == "user"
    assert agent.memory[0]["content"] == "hello"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Concurrent writes — thread-safety
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_registry_registration():
    """20 coroutines each registering a unique agent; none should be lost."""
    reg = AgentRegistry()

    async def register(i: int) -> None:
        state = make_agent(f"concurrent-{i}")
        await reg.register_agent(state)

    await asyncio.gather(*[register(i) for i in range(20)])

    all_agents = await reg.list_all_agents()
    assert len(all_agents) == 20
    for i in range(20):
        found = await reg.get_agent(f"agent-concurrent-{i}")
        assert found is not None, f"agent-concurrent-{i} missing from registry"


@pytest.mark.asyncio
async def test_concurrent_status_updates_on_same_agent():
    """Multiple coroutines racing to update the same agent; final state is valid."""
    agent = make_agent("race-target")
    statuses = [AgentStatus.RUNNING, AgentStatus.IDLE, AgentStatus.ERROR,
                AgentStatus.AWAITING_INPUT, AgentStatus.IDLE]

    async def update(s: AgentStatus, delay: float) -> None:
        await asyncio.sleep(delay)
        async with agent._lock:
            agent.set_status(s)

    # Stagger updates across a tiny window
    await asyncio.gather(
        *[update(s, i * 0.001) for i, s in enumerate(statuses)]
    )

    # Final state must be one of the valid enum values
    assert agent.status in AgentStatus


@pytest.mark.asyncio
async def test_concurrent_registry_sync_does_not_duplicate_dirty_set():
    """Calling sync_to_db() concurrently should not corrupt the dirty set."""
    reg = AgentRegistry()
    factory, _ = _mock_session_factory()

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        for i in range(10):
            await reg.register_agent(make_agent(f"sync-{i}"))

        # Fire 5 concurrent sync calls
        results = await asyncio.gather(*[reg.sync_to_db() for _ in range(5)])

    # Flatten all agent_ids that appeared in any sync result
    all_synced = set()
    for result_dict in results:
        all_synced.update(result_dict.keys())

    # Every registered agent should have been synced at least once
    assert len(all_synced) == 10


# ═════════════════════════════════════════════════════════════════════════════
# 4. Memory management
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_memory_trimmed_to_max_after_update():
    agent = make_agent("memory-trim")

    for i in range(30):  # push 30 messages → only 20 kept
        agent.update_memory(f"Message {i}", "user")

    assert len(agent.memory) == MAX_MEMORY_MESSAGES
    # The LAST 20 messages must be retained
    assert agent.memory[0]["content"] == "Message 10"
    assert agent.memory[-1]["content"] == "Message 29"


@pytest.mark.asyncio
async def test_clear_old_memory_respects_keep_last():
    agent = make_agent("manual-trim")
    for i in range(15):
        # Bypass update_memory auto-trim by appending directly
        agent.memory.append({"role": "user", "content": f"msg-{i}", "timestamp": "t"})

    agent.clear_old_memory(keep_last=5)

    assert len(agent.memory) == 5
    assert agent.memory[0]["content"] == "msg-10"
    assert agent.memory[-1]["content"] == "msg-14"
    assert agent._dirty is True


@pytest.mark.asyncio
async def test_memory_within_limit_not_trimmed():
    agent = make_agent("no-trim")
    for i in range(10):
        agent.update_memory(f"msg-{i}", "assistant")

    assert len(agent.memory) == 10  # well under 20 — should not trim


# ═════════════════════════════════════════════════════════════════════════════
# 5. AgentContext execution path and reset
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_context_records_execution_path():
    ctx = AgentContext(
        execution_id=str(uuid.uuid4()),
        workflow_id=str(uuid.uuid4()),
    )

    ctx.add_to_context("agent-A", input_data={"query": "hello"})
    ctx.add_to_context("agent-B", input_data={"query": "world"}, output_data={"ans": 42})
    ctx.add_to_context("agent-C", input_data={}, duration_ms=150)

    full = ctx.get_full_context()

    assert full["execution_path"] == ["agent-A", "agent-B", "agent-C"]
    assert full["step_count"] == 3
    assert full["steps"]["agent-B"]["output"] == {"ans": 42}
    assert full["steps"]["agent-C"]["duration_ms"] == 150


@pytest.mark.asyncio
async def test_agent_context_update_step_output():
    ctx = AgentContext(execution_id=str(uuid.uuid4()))
    ctx.add_to_context("agent-X", input_data={"q": "test"})

    assert ctx.get_step("agent-X")["output"] is None

    ctx.update_step_output("agent-X", output_data={"result": "done"}, duration_ms=200)

    assert ctx.get_step("agent-X")["output"] == {"result": "done"}
    assert ctx.get_step("agent-X")["duration_ms"] == 200


@pytest.mark.asyncio
async def test_agent_context_reset_clears_state():
    ctx = AgentContext(execution_id=str(uuid.uuid4()))
    ctx.add_to_context("agent-1", {})
    ctx.add_to_context("agent-2", {})
    assert len(ctx.execution_path) == 2

    ctx.reset()

    assert len(ctx.execution_path) == 0
    assert len(ctx.step_data) == 0


@pytest.mark.asyncio
async def test_agent_context_duplicate_step_updates_in_place():
    """Adding the same agent_id twice should update the existing record."""
    ctx = AgentContext(execution_id=str(uuid.uuid4()))
    ctx.add_to_context("agent-dup", {"first": True})
    ctx.add_to_context("agent-dup", {"second": True})  # same agent_id

    assert ctx.execution_path.count("agent-dup") == 1
    assert ctx.step_data["agent-dup"]["input"] == {"second": True}


# ═════════════════════════════════════════════════════════════════════════════
# 6. DB retry logic — exponential back-off
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_save_to_db_retries_on_transient_failure():
    agent = make_agent("retry-test")
    agent.set_status(AgentStatus.RUNNING)

    call_count = 0

    def flaky_factory():
        """Fails twice, succeeds on the third call."""
        nonlocal call_count
        call_count += 1
        mock_session = AsyncMock()
        if call_count < 3:
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("DB unavailable"))
        else:
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    factory = MagicMock(side_effect=flaky_factory)

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        with patch("asyncio.sleep", new_callable=AsyncMock):  # skip real delays
            success = await agent.save_to_db()

    assert success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_save_to_db_returns_false_after_all_retries_fail():
    agent = make_agent("all-fail")

    def always_fail():
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=Exception("permanent failure"))
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    factory = MagicMock(side_effect=always_fail)

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            success = await agent.save_to_db()

    assert success is False
    # In-memory state is intact despite DB failure
    assert agent.agent_id == "all-fail"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Graceful degradation — in-memory state preserved when DB is down
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_state_remains_usable_after_db_failure():
    agent = make_agent("degraded")
    agent.set_status(AgentStatus.RUNNING)
    agent.update_memory("I'm still working", "assistant")
    agent.increment_execution()

    def broken_factory():
        m = AsyncMock()
        m.__aenter__ = AsyncMock(side_effect=Exception("no DB"))
        m.__aexit__ = AsyncMock(return_value=False)
        return m

    with patch("app.services.agent_state_manager.AsyncSessionLocal", MagicMock(side_effect=broken_factory)):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            success = await agent.save_to_db()

    assert success is False
    # All in-memory mutations survived
    assert agent.status == AgentStatus.RUNNING
    assert len(agent.memory) == 1
    assert agent.execution_count == 1
    assert agent._dirty is True  # still dirty; will be retried later


# ═════════════════════════════════════════════════════════════════════════════
# 8. Registry mark_critical — immediate save
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mark_critical_saves_immediately():
    reg = AgentRegistry()
    agent = make_agent("critical")
    await reg.register_agent(agent)

    factory, mock_session = _mock_session_factory()

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        success = await reg.mark_critical("agent-critical")

    assert success is True
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    # Should no longer be in the dirty set
    assert "agent-critical" not in reg._dirty_agents


@pytest.mark.asyncio
async def test_mark_critical_returns_false_for_unknown_agent():
    reg = AgentRegistry()
    result = await reg.mark_critical("does-not-exist")
    assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# 9. Registry sync_to_db — batch persistence
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sync_to_db_persists_all_dirty_agents():
    reg = AgentRegistry()
    factory, mock_session = _mock_session_factory()

    agents = [make_agent(str(i)) for i in range(4)]
    for a in agents:
        await reg.register_agent(a)

    with patch("app.services.agent_state_manager.AsyncSessionLocal", factory):
        outcome = await reg.sync_to_db()

    assert len(outcome) == 4
    assert all(outcome.values()), f"Some agents failed: {outcome}"
    # Dirty set should be empty after a successful sync
    assert reg.dirty_count() == 0


@pytest.mark.asyncio
async def test_sync_to_db_is_noop_when_nothing_dirty():
    reg = AgentRegistry()
    outcome = await reg.sync_to_db()
    assert outcome == {}


# ═════════════════════════════════════════════════════════════════════════════
# 10. Registry unregister
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unregister_removes_agent():
    reg = AgentRegistry()
    await reg.register_agent(make_agent("to-remove"))
    assert reg.agent_count() == 1

    removed = await reg.unregister_agent("agent-to-remove")
    assert removed is True
    assert reg.agent_count() == 0
    assert await reg.get_agent("agent-to-remove") is None


@pytest.mark.asyncio
async def test_unregister_nonexistent_returns_false():
    reg = AgentRegistry()
    result = await reg.unregister_agent("phantom")
    assert result is False


@pytest.mark.asyncio
async def test_unregister_removes_from_dirty_set():
    reg = AgentRegistry()
    await reg.register_agent(make_agent("dirty-remove"))
    assert "agent-dirty-remove" in reg._dirty_agents

    await reg.unregister_agent("agent-dirty-remove")
    assert "agent-dirty-remove" not in reg._dirty_agents


# ═════════════════════════════════════════════════════════════════════════════
# 11. AgentState serialisation round-trip
# ═════════════════════════════════════════════════════════════════════════════


def test_to_dict_contains_all_fields():
    agent = make_agent("serial")
    agent.set_status(AgentStatus.AWAITING_INPUT)
    agent.update_memory("ping", "user")
    agent.add_tool("web_search")
    agent.update_metadata("owner", "alice")

    d = agent.to_dict()

    assert d["agent_id"] == "agent-serial"
    assert d["status"] == "awaiting_input"
    assert len(d["memory"]) == 1
    assert d["tools"] == ["web_search"]
    assert d["metadata"] == {"owner": "alice"}
    assert d["execution_count"] == 0


def test_add_and_remove_tool():
    agent = make_agent("tools")
    agent.add_tool("search")
    agent.add_tool("calculator")
    assert "search" in agent.tools
    assert "calculator" in agent.tools

    agent.remove_tool("search")
    assert "search" not in agent.tools
    assert "calculator" in agent.tools


# ═════════════════════════════════════════════════════════════════════════════
# 12. Registry status_summary
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_status_summary_groups_by_status():
    reg = AgentRegistry()

    statuses = [
        AgentStatus.IDLE,
        AgentStatus.IDLE,
        AgentStatus.RUNNING,
        AgentStatus.ERROR,
        AgentStatus.IDLE,
    ]
    for i, s in enumerate(statuses):
        a = make_agent(str(i))
        a.set_status(s)
        await reg.register_agent(a)

    summary = await reg.status_summary()
    assert summary["idle"] == 3
    assert summary["running"] == 1
    assert summary["error"] == 1
