"""
Orchestrator test suite
════════════════════════════════════════════════════════════════════════════════

Scenarios covered
─────────────────
 1.  Sequential workflow  A → B → C
 2.  Parallel workflow    A, B run together → C waits for both
 3.  Conditional branch   A → cond → (true: B, false: C)  — each direction
 4.  Error + retry        node fails twice, succeeds on 3rd attempt
 5.  All-retries-fail     node exhausts retries → NodeResult.failed
 6.  Circuit breaker      3 rapid failures → workflow halted
 7.  Stop workflow        graceful cancellation mid-run
 8.  Output propagation   each node receives previous node's output
 9.  Parallel output      both parallel nodes' outputs available to merge node
10.  Condition eval       direct unit-tests of handle_condition()
11.  DAG validator        cycles, unknown refs, missing fields raise ValueError
12.  Performance          10-node workflow completes in <5 s

All tests use a mock agent executor; no live DB or registry needed.
"""

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.dag_models import (
    DagNode,
    NodeStatus,
    NodeType,
    WorkflowDag,
    parse_dag,
)
from app.services.orchestrator import (
    CB_FAILURE_THRESHOLD,
    MAX_NODE_RETRIES,
    WorkflowOrchestrator,
    WorkflowRun,
    _Namespace,
)

# ─────────────────────────────── Fixtures / Helpers ──────────────────────────


def _make_orchestrator(executor=None) -> WorkflowOrchestrator:
    """Return an orchestrator with a mock registry and optional custom executor."""
    mock_registry = MagicMock()
    mock_registry.get_or_load = AsyncMock(return_value=None)
    mock_registry.mark_dirty = AsyncMock()
    return WorkflowOrchestrator(registry=mock_registry, agent_executor=executor)


def _instant_executor(output_fn=None, delay: float = 0.0):
    """Return an async executor that responds immediately (or after *delay* s)."""
    async def executor(agent_id: str, input_data: Dict, context: Dict) -> Dict:
        if delay:
            await asyncio.sleep(delay)
        if output_fn:
            return output_fn(agent_id, input_data, context)
        return {"agent_id": agent_id, "done": True}
    return executor


async def _run(dag_config: Dict, input_data: Dict = None, executor=None) -> WorkflowRun:
    """Helper: build an orchestrator, run *dag_config*, await completion."""
    orch = _make_orchestrator(executor or _instant_executor())
    with _patch_db():
        run = await orch.execute_workflow(
            workflow_id="wf-test",
            input_data=input_data or {},
            dag_config=dag_config,
            background=False,
        )
    return run


def _patch_db():
    """Context manager that stubs all DB calls in the orchestrator."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        with patch(
            "app.services.orchestrator.AsyncSessionLocal",
            _mock_session_factory(),
        ):
            yield

    return ctx()


def _mock_session_factory():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=mock_session)
    return factory


# ═════════════════════════════════════════════════════════════════════════════
# 1. Sequential workflow
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sequential_abc():
    """A → B → C all succeed in order."""
    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a1", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "a2", "depends_on": ["A"]},
            {"id": "C", "type": "agent", "agent_id": "a3", "depends_on": ["B"]},
        ]
    }
    run = await _run(dag)

    assert run.status == "completed"
    assert run.node_results["A"].succeeded
    assert run.node_results["B"].succeeded
    assert run.node_results["C"].succeeded


@pytest.mark.asyncio
async def test_sequential_execution_order():
    """B must see A's output; C must see B's output."""
    order: list[str] = []

    async def executor(agent_id, input_data, context):
        order.append(agent_id)
        return {"ran": agent_id}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a1", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "a2", "depends_on": ["A"]},
            {"id": "C", "type": "agent", "agent_id": "a3", "depends_on": ["B"]},
        ]
    }
    run = await _run(dag, executor=executor)

    assert order == ["a1", "a2", "a3"]
    # B receives A's output as input["input"]
    b_input = run.node_results["B"].input_data
    assert b_input["input"] == {"ran": "a1"}
    c_input = run.node_results["C"].input_data
    assert c_input["input"] == {"ran": "a2"}


# ═════════════════════════════════════════════════════════════════════════════
# 2. Parallel workflow
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_parallel_nodes_run_concurrently():
    """A and B (no deps) start together; C waits for both."""
    start_times: dict[str, float] = {}
    end_times: dict[str, float] = {}

    async def executor(agent_id, input_data, context):
        start_times[agent_id] = time.monotonic()
        await asyncio.sleep(0.05)  # 50 ms work
        end_times[agent_id] = time.monotonic()
        return {"agent": agent_id}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a1", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "a2", "depends_on": []},
            {"id": "C", "type": "agent", "agent_id": "a3", "depends_on": ["A", "B"]},
        ]
    }
    run = await _run(dag, executor=executor)

    assert run.status == "completed"
    # A and B must overlap: A starts before B ends and B starts before A ends
    assert start_times["a1"] < end_times["a2"]
    assert start_times["a2"] < end_times["a1"]
    # C runs after both finish
    assert start_times["a3"] >= max(end_times["a1"], end_times["a2"])


@pytest.mark.asyncio
async def test_parallel_outputs_merged_for_downstream():
    """Node C receives both A's and B's outputs in dep_outputs."""

    async def executor(agent_id, input_data, context):
        return {"from": agent_id}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a1", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "a2", "depends_on": []},
            {"id": "C", "type": "agent", "agent_id": "a3", "depends_on": ["A", "B"]},
        ]
    }
    run = await _run(dag, executor=executor)

    c_input = run.node_results["C"].input_data
    assert c_input["dep_outputs"]["A"] == {"from": "a1"}
    assert c_input["dep_outputs"]["B"] == {"from": "a2"}


# ═════════════════════════════════════════════════════════════════════════════
# 3. Conditional branching
# ═════════════════════════════════════════════════════════════════════════════


def _cond_dag(score: float) -> Dict:
    """DAG: extract → route (condition) → send_email or queue_review"""
    return {
        "nodes": [
            {
                "id": "extract",
                "type": "agent",
                "agent_id": "extractor",
                "depends_on": [],
            },
            {
                "id": "route",
                "type": "condition",
                "condition": "output.score > 0.8",
                "depends_on": ["extract"],
                "true_branch": "send_email",
                "false_branch": "queue_review",
            },
            {
                "id": "send_email",
                "type": "agent",
                "agent_id": "emailer",
                "depends_on": ["route"],
            },
            {
                "id": "queue_review",
                "type": "agent",
                "agent_id": "reviewer",
                "depends_on": ["route"],
            },
        ]
    }


@pytest.mark.asyncio
async def test_condition_true_branch_runs():
    """score=0.9 → true branch (send_email) runs, queue_review is skipped."""
    async def executor(agent_id, input_data, context):
        return {"score": 0.9}  # extract returns this

    run = await _run(_cond_dag(0.9), executor=executor)

    assert run.status == "completed"
    assert run.node_results["send_email"].succeeded
    assert run.node_results["queue_review"].status == NodeStatus.SKIPPED


@pytest.mark.asyncio
async def test_condition_false_branch_runs():
    """score=0.5 → false branch (queue_review) runs, send_email is skipped."""
    async def executor(agent_id, input_data, context):
        if agent_id == "extractor":
            return {"score": 0.5}
        return {"done": True}

    run = await _run(_cond_dag(0.5), executor=executor)

    assert run.status == "completed"
    assert run.node_results["queue_review"].succeeded
    assert run.node_results["send_email"].status == NodeStatus.SKIPPED


@pytest.mark.asyncio
async def test_condition_with_nested_attribute():
    """output.metadata.priority uses nested dict access."""
    orch = _make_orchestrator()
    result = orch.handle_condition(
        "output.metadata.priority > 5",
        {"output": {"metadata": {"priority": 9}}, "workflow_input": {}},
    )
    assert result is True

    result2 = orch.handle_condition(
        "output.metadata.priority > 5",
        {"output": {"metadata": {"priority": 2}}, "workflow_input": {}},
    )
    assert result2 is False


# ═════════════════════════════════════════════════════════════════════════════
# 4. Retry logic — success on 3rd attempt
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt():
    """Node fails twice then succeeds; result shows attempts=3."""
    call_count = 0

    async def flaky(agent_id, input_data, context):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError(f"transient failure #{call_count}")
        return {"recovered": True}

    dag = {"nodes": [{"id": "X", "type": "agent", "agent_id": "x", "depends_on": []}]}

    with patch("app.services.orchestrator._RETRY_DELAYS", [0.0, 0.0, 0.0]):
        run = await _run(dag, executor=flaky)

    assert run.status == "completed"
    assert run.node_results["X"].succeeded
    assert run.node_results["X"].attempts == 3
    assert call_count == 3


# ═════════════════════════════════════════════════════════════════════════════
# 5. All retries fail
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_retries_exhausted():
    """Node always raises → NodeResult.failed after MAX_NODE_RETRIES attempts."""
    call_count = 0

    async def always_fail(agent_id, input_data, context):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("permanent error")

    dag = {"nodes": [{"id": "Y", "type": "agent", "agent_id": "y", "depends_on": []}]}

    with patch("app.services.orchestrator._RETRY_DELAYS", [0.0, 0.0, 0.0]):
        run = await _run(dag, executor=always_fail)

    assert run.status == "failed"
    assert run.node_results["Y"].failed
    assert run.node_results["Y"].attempts == MAX_NODE_RETRIES
    assert call_count == MAX_NODE_RETRIES


@pytest.mark.asyncio
async def test_failed_node_skips_dependents():
    """If A fails, B and C (which depend on A) should be skipped."""

    async def fail_a(agent_id, input_data, context):
        if agent_id == "a":
            raise RuntimeError("A failed")
        return {"ok": True}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": ["A"]},
            {"id": "C", "type": "agent", "agent_id": "c", "depends_on": ["B"]},
        ]
    }

    with patch("app.services.orchestrator._RETRY_DELAYS", [0.0, 0.0, 0.0]):
        run = await _run(dag, executor=fail_a)

    assert run.node_results["A"].failed
    assert run.node_results["B"].status == NodeStatus.SKIPPED
    assert run.node_results["C"].status == NodeStatus.SKIPPED


# ═════════════════════════════════════════════════════════════════════════════
# 6. Circuit breaker
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_circuit_breaker_halts_workflow():
    """3 rapid node failures → workflow status becomes 'halted'."""
    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": []},
            {"id": "C", "type": "agent", "agent_id": "c", "depends_on": []},
        ]
    }

    async def always_fail(agent_id, input_data, context):
        raise RuntimeError("cb test failure")

    with patch("app.services.orchestrator._RETRY_DELAYS", [0.0, 0.0, 0.0]):
        run = await _run(dag, executor=always_fail)

    assert run.status == "halted"
    assert run.error and "Circuit breaker" in run.error


@pytest.mark.asyncio
async def test_circuit_breaker_count():
    """Verify the breaker fires exactly at CB_FAILURE_THRESHOLD failures."""
    orch = _make_orchestrator()
    run = WorkflowRun(
        execution_id="test", workflow_id="wf", input_data={}
    )
    # Simulate failures one by one
    for i in range(CB_FAILURE_THRESHOLD - 1):
        tripped = orch._check_circuit_breaker(run, f"node-{i}")
        assert not tripped, f"Breaker tripped too early at failure {i + 1}"

    # The CB_FAILURE_THRESHOLD-th failure trips it
    tripped = orch._check_circuit_breaker(run, "node-final")
    assert tripped


# ═════════════════════════════════════════════════════════════════════════════
# 7. Stop workflow
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stop_workflow_signals_run():
    """stop_workflow() sets the stop event on the active run."""
    orch = _make_orchestrator()
    run = WorkflowRun(execution_id="e1", workflow_id="wf", input_data={})
    orch._active_runs["e1"] = run

    result = await orch.stop_workflow("e1")

    assert result is True
    assert run.is_stopped


@pytest.mark.asyncio
async def test_stop_unknown_execution_returns_false():
    orch = _make_orchestrator()
    result = await orch.stop_workflow("does-not-exist")
    assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# 8. Output propagation (sequential chain)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_propagation_chain():
    """Each node transforms the previous output; C sees B's output."""
    async def executor(agent_id, input_data, context):
        prev = input_data.get("input", {})
        n = (prev.get("n", 0) if isinstance(prev, dict) else 0)
        return {"n": n + 1}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": ["A"]},
            {"id": "C", "type": "agent", "agent_id": "c", "depends_on": ["B"]},
        ]
    }
    run = await _run(dag, executor=executor)

    assert run.node_results["A"].output == {"n": 1}
    assert run.node_results["B"].output == {"n": 2}
    assert run.node_results["C"].output == {"n": 3}


@pytest.mark.asyncio
async def test_workflow_input_always_available():
    """Every node receives the original workflow_input regardless of position."""
    received_inputs = {}

    async def executor(agent_id, input_data, context):
        received_inputs[agent_id] = input_data.get("workflow_input")
        return {"ok": True}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": ["A"]},
        ]
    }
    run = await _run(dag, input_data={"trigger": "go"}, executor=executor)

    assert received_inputs["a"] == {"trigger": "go"}
    assert received_inputs["b"] == {"trigger": "go"}


# ═════════════════════════════════════════════════════════════════════════════
# 9. Condition eval unit tests
# ═════════════════════════════════════════════════════════════════════════════


def test_condition_eval_simple_comparison():
    orch = _make_orchestrator()
    assert orch.handle_condition("output.score > 0.8", {"output": {"score": 0.9}}) is True
    assert orch.handle_condition("output.score > 0.8", {"output": {"score": 0.5}}) is False


def test_condition_eval_equality():
    orch = _make_orchestrator()
    assert orch.handle_condition("output.status == 'approved'",
                                  {"output": {"status": "approved"}}) is True
    assert orch.handle_condition("output.status == 'approved'",
                                  {"output": {"status": "rejected"}}) is False


def test_condition_eval_boolean_operators():
    orch = _make_orchestrator()
    ctx = {"output": {"a": 10, "b": 5}}
    assert orch.handle_condition("output.a > 8 and output.b < 10", ctx) is True
    assert orch.handle_condition("output.a < 5 or output.b < 10", ctx) is True
    assert orch.handle_condition("output.a < 5 or output.b > 10", ctx) is False


def test_condition_eval_with_workflow_input():
    orch = _make_orchestrator()
    ctx = {"output": {"score": 0.7}, "workflow_input": {"threshold": 0.6}}
    assert orch.handle_condition(
        "output.score > workflow_input.threshold", ctx
    ) is True


def test_condition_eval_bad_expression_defaults_false():
    orch = _make_orchestrator()
    result = orch.handle_condition("import os", {"output": {}})
    assert result is False  # syntax error in eval → defaults to False


def test_namespace_attribute_access():
    ns = _Namespace({"score": 0.9, "tags": {"priority": "high"}})
    assert ns.score._Namespace__dict__ if hasattr(ns.score, "_Namespace__dict__") else True
    # Numeric comparison
    assert (ns.score > 0.8) is True
    assert (ns.score < 0.5) is False
    # Nested access
    assert ns.tags.priority == "high"


# ═════════════════════════════════════════════════════════════════════════════
# 10. DAG validation
# ═════════════════════════════════════════════════════════════════════════════


def test_parse_dag_valid():
    dag = parse_dag({
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a1", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "a2", "depends_on": ["A"]},
        ]
    })
    assert len(dag.nodes) == 2
    assert dag.nodes["B"].depends_on == ["A"]


def test_parse_dag_rejects_unknown_dep():
    with pytest.raises(ValueError, match="unknown node"):
        parse_dag({
            "nodes": [
                {"id": "A", "type": "agent", "agent_id": "a", "depends_on": ["GHOST"]},
            ]
        })


def test_parse_dag_rejects_cycle():
    with pytest.raises(ValueError, match="cycle"):
        parse_dag({
            "nodes": [
                {"id": "A", "type": "agent", "agent_id": "a", "depends_on": ["B"]},
                {"id": "B", "type": "agent", "agent_id": "b", "depends_on": ["A"]},
            ]
        })


def test_parse_dag_rejects_agent_node_without_agent_id():
    with pytest.raises(ValueError, match="agent_id"):
        parse_dag({
            "nodes": [{"id": "X", "type": "agent", "depends_on": []}]
        })


def test_parse_dag_rejects_condition_without_expression():
    with pytest.raises(ValueError, match="condition"):
        parse_dag({
            "nodes": [
                {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
                {
                    "id": "cond",
                    "type": "condition",
                    "depends_on": ["A"],
                    "true_branch": "X",
                    "false_branch": "Y",
                },
            ]
        })


def test_parse_dag_rejects_condition_unknown_branch():
    with pytest.raises(ValueError, match="true_branch"):
        parse_dag({
            "nodes": [
                {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
                {
                    "id": "cond",
                    "type": "condition",
                    "condition": "output.x > 0",
                    "depends_on": ["A"],
                    "true_branch": "NONEXISTENT",
                    "false_branch": "A",
                },
            ]
        })


def test_dag_execution_levels():
    dag = parse_dag({
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": []},
            {"id": "C", "type": "agent", "agent_id": "c", "depends_on": ["A", "B"]},
        ]
    })
    levels = dag.execution_levels()
    assert sorted(levels[0]) == ["A", "B"]
    assert levels[1] == ["C"]


# ═════════════════════════════════════════════════════════════════════════════
# 11. Performance: 10-node workflow < 5 s
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ten_node_workflow_completes_under_5s():
    """
    Topology: level-0 has 5 parallel nodes (10ms each); level-1 has 5 nodes
    each depending on one level-0 node (10ms each).
    Total wall time ≈ 20 ms — well under 5 s.
    """
    dag_config = {
        "nodes": [
            # Level 0 — 5 parallel nodes
            {"id": f"l0_{i}", "type": "agent", "agent_id": f"a{i}", "depends_on": []}
            for i in range(5)
        ] + [
            # Level 1 — each depends on the matching level-0 node
            {
                "id": f"l1_{i}",
                "type": "agent",
                "agent_id": f"b{i}",
                "depends_on": [f"l0_{i}"],
            }
            for i in range(5)
        ]
    }

    async def fast_executor(agent_id, input_data, context):
        await asyncio.sleep(0.01)  # 10 ms simulated work
        return {"done": agent_id}

    t0 = time.perf_counter()
    run = await _run(dag_config, executor=fast_executor)
    elapsed = time.perf_counter() - t0

    assert run.status == "completed", f"Workflow failed: {run.error}"
    assert len(run.node_results) == 10
    assert all(r.succeeded for r in run.node_results.values())
    assert elapsed < 5.0, f"10-node workflow took {elapsed:.2f}s (limit: 5s)"


# ═════════════════════════════════════════════════════════════════════════════
# 12. Empty / edge-case DAGs
# ═════════════════════════════════════════════════════════════════════════════


def test_parse_empty_dag_raises():
    with pytest.raises(ValueError, match="empty|no nodes"):
        parse_dag({})


def test_parse_dag_with_no_nodes_raises():
    with pytest.raises(ValueError):
        parse_dag({"nodes": []})


@pytest.mark.asyncio
async def test_single_node_workflow():
    dag = {"nodes": [{"id": "only", "type": "agent", "agent_id": "solo", "depends_on": []}]}
    run = await _run(dag, input_data={"x": 1})
    assert run.status == "completed"
    assert run.node_results["only"].succeeded


# ═════════════════════════════════════════════════════════════════════════════
# 13. Complex branching: condition with downstream merge (diamond)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_diamond_parallel_then_merge():
    """
    A → B, A → C → D (B and C run in parallel after A, then D waits for both).
    """
    order: list[str] = []

    async def executor(agent_id, input_data, context):
        order.append(agent_id)
        await asyncio.sleep(0.01)
        return {"from": agent_id}

    dag = {
        "nodes": [
            {"id": "A", "type": "agent", "agent_id": "a", "depends_on": []},
            {"id": "B", "type": "agent", "agent_id": "b", "depends_on": ["A"]},
            {"id": "C", "type": "agent", "agent_id": "c", "depends_on": ["A"]},
            {"id": "D", "type": "agent", "agent_id": "d", "depends_on": ["B", "C"]},
        ]
    }
    run = await _run(dag, executor=executor)

    assert run.status == "completed"
    assert order[0] == "a"
    assert set(order[1:3]) == {"b", "c"}
    assert order[3] == "d"
    d_deps = run.node_results["D"].input_data["dep_outputs"]
    assert "B" in d_deps and "C" in d_deps
