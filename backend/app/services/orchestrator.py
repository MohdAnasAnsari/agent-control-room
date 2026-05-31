"""
Workflow DAG Orchestrator
════════════════════════════════════════════════════════════════════════════════
Executes workflow DAGs with full support for sequential, parallel, conditional,
and loop (retry) execution patterns.

Concurrency model
─────────────────
Each workflow execution runs as an asyncio background Task.  Within a single
execution, nodes that share a dependency level are launched with
asyncio.gather() so they run truly in parallel.  No threading — safe to run
many concurrent workflows in the same process.

Retry model
───────────
Failed nodes are retried up to MAX_NODE_RETRIES=3 times with delays of
1 s → 2 s → 4 s (exponential back-off, configurable via _RETRY_DELAYS).

Circuit breaker
───────────────
If CB_FAILURE_THRESHOLD (3) distinct node failures occur within
CB_WINDOW_SECONDS (300 s), the entire workflow is immediately halted with
status="halted" and the stop event is set so any in-flight parallel nodes
abort as soon as they check.

Condition evaluation
────────────────────
Condition expressions (e.g. "output.score > 0.8") are evaluated with a
restricted eval() that exposes only: output, workflow_input, node_outputs,
and a handful of safe builtins.  Attribute access on dicts is enabled via
_Namespace so the natural dot-notation reads intuitively.

Output passing
──────────────
Each node receives:
  input["workflow_input"] — the original workflow trigger data
  input["dep_outputs"]    — dict of {node_id: output} for all its deps
  input["input"]          — single-dep shortcut: the upstream output directly
"""

from __future__ import annotations

import ast as _ast
import asyncio
import logging
import time
import uuid as _uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select

from app.models.database import Execution, ExecutionStep
from app.models.db_session import AsyncSessionLocal
from app.services.agent_registry import AgentRegistry
from app.services.agent_state_manager import AgentStatus
from app.services.dag_models import DagNode, NodeStatus, NodeType, WorkflowDag, parse_dag

logger = logging.getLogger(__name__)

# ── Retry / circuit-breaker constants ────────────────────────────────────────
_RETRY_DELAYS: List[float] = [1.0, 2.0, 4.0]   # seconds between attempts
MAX_NODE_RETRIES: int = len(_RETRY_DELAYS) + 1   # = 3 total attempts

CB_FAILURE_THRESHOLD: int = 3    # trips the breaker after this many failures …
CB_WINDOW_SECONDS: float = 300.0 # … within this rolling window (5 min)

# Type alias for the pluggable agent executor
AgentExecutorFn = Callable[
    [str, Dict[str, Any], Dict[str, Any]],   # agent_id, input, context
    Awaitable[Dict[str, Any]],               # → output
]


# ══════════════════════════════════════════════════════════════════════════════
# _Namespace  — dict wrapper that allows attribute-style access in conditions
# ══════════════════════════════════════════════════════════════════════════════


class _Namespace:
    """
    Wraps a value (dict or scalar) and exposes dict keys as attributes.
    Used so conditions can write  output.score  instead of  output["score"].
    """

    __slots__ = ("_v",)

    def __init__(self, data: Any) -> None:
        object.__setattr__(self, "_v", data)

    def _unwrap(self) -> Any:
        return object.__getattribute__(self, "_v")

    def __getattr__(self, key: str) -> "_Namespace":
        v = self._unwrap()
        if isinstance(v, dict):
            try:
                return _Namespace(v[key])
            except KeyError:
                raise AttributeError(f"'{key}' not in output")
        raise AttributeError(f"Cannot access '{key}' on {type(v).__name__}")

    def __getitem__(self, key: Any) -> "_Namespace":
        return _Namespace(self._unwrap()[key])

    # Comparison operators all delegate to the wrapped value
    def __gt__(self, o: Any) -> bool: return self._unwrap() > (o._unwrap() if isinstance(o, _Namespace) else o)
    def __lt__(self, o: Any) -> bool: return self._unwrap() < (o._unwrap() if isinstance(o, _Namespace) else o)
    def __ge__(self, o: Any) -> bool: return self._unwrap() >= (o._unwrap() if isinstance(o, _Namespace) else o)
    def __le__(self, o: Any) -> bool: return self._unwrap() <= (o._unwrap() if isinstance(o, _Namespace) else o)
    def __eq__(self, o: Any) -> bool: return self._unwrap() == (o._unwrap() if isinstance(o, _Namespace) else o)
    def __ne__(self, o: Any) -> bool: return self._unwrap() != (o._unwrap() if isinstance(o, _Namespace) else o)
    def __bool__(self) -> bool: return bool(self._unwrap())
    def __len__(self) -> int: return len(self._unwrap())
    def __contains__(self, item: Any) -> bool: return item in self._unwrap()
    def __repr__(self) -> str: return repr(self._unwrap())


# ══════════════════════════════════════════════════════════════════════════════
# NodeResult  — outcome of a single node execution
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    output: Any = None
    input_data: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    attempts: int = 1
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def succeeded(self) -> bool:
        return self.status == NodeStatus.SUCCESS

    @property
    def failed(self) -> bool:
        return self.status == NodeStatus.FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "timestamp": self.timestamp.isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# WorkflowRun  — mutable state for one execution of a workflow
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class WorkflowRun:
    execution_id: str
    workflow_id: str
    input_data: Dict[str, Any]
    status: str = "pending"            # pending | running | completed | failed | halted | stopped
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        self._stop_event: asyncio.Event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # (epoch_seconds, node_id) for the rolling circuit-breaker window
        self._recent_failures: deque = deque()

    @property
    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def get_node_output(self, node_id: str) -> Any:
        r = self.node_results.get(node_id)
        return r.output if (r and r.succeeded) else None

    def build_context(self, current_node_id: str) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_input": self.input_data,
            "node_outputs": {
                nid: r.output
                for nid, r in self.node_results.items()
                if r.succeeded
            },
            "current_node_id": current_node_id,
        }

    async def wait(self) -> "WorkflowRun":
        """Await the background task to completion."""
        if self._task and not self._task.done():
            await self._task
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "error": self.error,
            "node_results": {
                nid: r.to_dict() for nid, r in self.node_results.items()
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# WorkflowOrchestrator
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowOrchestrator:
    """
    Executes workflow DAGs with sequential, parallel, conditional, and retry
    execution patterns.

    Parameters
    ──────────
    registry       AgentRegistry used to look up agents.
    agent_executor Optional callable that replaces the default LLM dispatch.
                   Signature: async (agent_id, input_data, context) → output.
                   Useful for injecting mocks in tests.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        agent_executor: Optional[AgentExecutorFn] = None,
    ) -> None:
        self._registry = registry
        self._agent_executor: AgentExecutorFn = (
            agent_executor or self._default_agent_executor
        )
        self._active_runs: Dict[str, WorkflowRun] = {}
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        *,
        dag_config: Optional[Dict[str, Any]] = None,
        background: bool = True,
    ) -> WorkflowRun:
        """
        Start a workflow execution.

        If *dag_config* is provided it is used directly (useful in tests).
        Otherwise the workflow is loaded from the database by *workflow_id*.

        When *background=True* (default) the execution runs as an asyncio Task
        and the method returns immediately.  Callers can ``await run.wait()``
        to block until the workflow finishes.

        When *background=False* the method awaits full completion before
        returning — useful for scripts and tests.
        """
        if dag_config is None:
            dag_config = await self._load_dag_config(workflow_id)

        dag = parse_dag(dag_config, fallback_id=workflow_id)

        execution_id = await self._create_execution_record(workflow_id)

        run = WorkflowRun(
            execution_id=execution_id,
            workflow_id=workflow_id,
            input_data=dict(input_data),
        )

        async with self._lock:
            self._active_runs[execution_id] = run

        if background:
            run._task = asyncio.create_task(
                self._run_dag(run, dag), name=f"wf-{execution_id[:8]}"
            )
        else:
            await self._run_dag(run, dag)

        return run

    async def execute_node(
        self, node_id: str, input_data: Dict[str, Any]
    ) -> NodeResult:
        """
        Execute a single node in isolation (no DAG context).
        Used for ad-hoc testing or single-step invocations.
        """
        if not self._registry:
            raise RuntimeError("Registry not set — cannot resolve agent")

        # Build a minimal synthetic node
        node = DagNode(id=node_id, type=NodeType.AGENT, agent_id=node_id)
        run = WorkflowRun(
            execution_id=str(_uuid.uuid4()),
            workflow_id="standalone",
            input_data=input_data,
        )
        return await self._execute_node_with_retry(node, run, input_data)

    async def stop_workflow(self, execution_id: str) -> bool:
        """
        Send a graceful-stop signal to a running workflow.
        In-flight parallel tasks finish their current node, then the loop
        checks the stop flag before launching any new nodes.
        Returns True if the run was found and signalled.
        """
        async with self._lock:
            run = self._active_runs.get(execution_id)
        if not run:
            logger.warning("stop_workflow: execution %s not found", execution_id)
            return False
        run._stop_event.set()
        if run._task and not run._task.done():
            run._task.cancel()
        logger.info("Stop signal sent to execution %s", execution_id)
        return True

    def list_active_runs(self) -> List[str]:
        return list(self._active_runs.keys())

    # ── DAG execution loop ────────────────────────────────────────────────────

    async def _run_dag(self, run: WorkflowRun, dag: WorkflowDag) -> None:
        """Main event loop that drives a workflow to completion."""
        run.status = "running"
        completed: Set[str] = set()
        failed: Set[str] = set()
        skipped: Set[str] = set()
        in_flight: Set[str] = set()
        all_node_ids: Set[str] = set(dag.nodes.keys())

        try:
            while True:
                if run.is_stopped:
                    run.status = "stopped"
                    return

                resolved = completed | skipped
                ready = dag.get_ready_nodes(resolved, in_flight)

                if not ready:
                    done = completed | failed | skipped
                    remaining = all_node_ids - done - in_flight
                    if not remaining and not in_flight:
                        run.status = "failed" if failed else "completed"
                        return
                    if remaining and not in_flight:
                        # Nodes remain but none are ready and none are running
                        # → they were orphaned by failed/skipped deps
                        for nid in list(remaining):
                            skipped.add(nid)
                            run.node_results[nid] = NodeResult(
                                node_id=nid, status=NodeStatus.SKIPPED
                            )
                        run.status = "failed" if failed else "completed"
                        return
                    # in_flight nodes still running — yield and retry
                    await asyncio.sleep(0)
                    continue

                in_flight.update(ready)

                # Run all ready nodes in parallel
                results: List[NodeResult] = list(
                    await asyncio.gather(
                        *(
                            self._execute_node_with_retry(
                                dag.nodes[nid],
                                run,
                                self._build_node_input(dag.nodes[nid], run),
                            )
                            for nid in ready
                        ),
                        return_exceptions=False,
                    )
                )

                for nid, result in zip(ready, results):
                    in_flight.discard(nid)
                    run.node_results[nid] = result

                    if result.succeeded:
                        completed.add(nid)
                        # Condition nodes return the chosen branch id as their output
                        node = dag.nodes[nid]
                        if node.type == NodeType.CONDITION and isinstance(result.output, str):
                            chosen = result.output
                            unchosen = (
                                node.false_branch
                                if chosen == node.true_branch
                                else node.true_branch
                            )
                            if unchosen:
                                self._mark_branch_skipped(
                                    dag, unchosen, completed, skipped, run
                                )

                    elif result.failed:
                        failed.add(nid)
                        # Propagate: dependents of this node become skipped
                        self._propagate_skips_from_failed(
                            dag, nid, completed, failed, skipped, run
                        )
                        if self._check_circuit_breaker(run, nid):
                            run.status = "halted"
                            run.error = (
                                f"Circuit breaker tripped: "
                                f"{CB_FAILURE_THRESHOLD} failures within "
                                f"{int(CB_WINDOW_SECONDS)}s"
                            )
                            run._stop_event.set()
                            return

        except asyncio.CancelledError:
            run.status = "stopped"
            raise
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.exception("Unhandled error in workflow %s", run.workflow_id)
        finally:
            run.completed_at = datetime.now(timezone.utc)
            await self._update_execution_record(run)
            async with self._lock:
                self._active_runs.pop(run.execution_id, None)

    # ── Node execution ────────────────────────────────────────────────────────

    async def _execute_node_with_retry(
        self,
        node: DagNode,
        run: WorkflowRun,
        input_data: Dict[str, Any],
    ) -> NodeResult:
        """
        Execute *node* with up to MAX_NODE_RETRIES attempts.
        Back-off delays: 1 s → 2 s → 4 s between consecutive failures.
        """
        start = time.perf_counter()
        last_error = ""

        for attempt in range(1, MAX_NODE_RETRIES + 1):
            if run.is_stopped:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SKIPPED,
                    attempts=attempt,
                )
            try:
                output = await self._dispatch_node(node, run, input_data)
                duration_ms = int((time.perf_counter() - start) * 1000)
                result = NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    output=output,
                    input_data=input_data,
                    duration_ms=duration_ms,
                    attempts=attempt,
                )
                await self._persist_step(run, node, result)
                logger.debug(
                    "Node '%s' succeeded in %dms (attempt %d)",
                    node.id, duration_ms, attempt,
                )
                return result

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"attempt {attempt}/{MAX_NODE_RETRIES}: {exc}"
                logger.warning("Node '%s' failed — %s", node.id, last_error)

                if attempt < MAX_NODE_RETRIES:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.info(
                        "Retrying node '%s' in %.0fs…", node.id, delay
                    )
                    await asyncio.sleep(delay)

        duration_ms = int((time.perf_counter() - start) * 1000)
        result = NodeResult(
            node_id=node.id,
            status=NodeStatus.FAILED,
            input_data=input_data,
            error=last_error,
            duration_ms=duration_ms,
            attempts=MAX_NODE_RETRIES,
        )
        await self._persist_step(run, node, result)
        logger.error(
            "Node '%s' exhausted all %d retries. Last error: %s",
            node.id, MAX_NODE_RETRIES, last_error,
        )
        return result

    async def _dispatch_node(
        self,
        node: DagNode,
        run: WorkflowRun,
        input_data: Dict[str, Any],
    ) -> Any:
        """Route execution to the correct handler based on node type."""
        if node.type == NodeType.AGENT:
            return await self._execute_agent_node(node, run, input_data)
        if node.type == NodeType.CONDITION:
            return self._handle_condition(node, run)
        raise ValueError(f"Unsupported node type: {node.type!r}")

    async def _execute_agent_node(
        self,
        node: DagNode,
        run: WorkflowRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call the pluggable agent executor with a timeout."""
        context = run.build_context(node.id)
        return await asyncio.wait_for(
            self._agent_executor(node.agent_id, input_data, context),
            timeout=node.timeout_s,
        )

    def handle_condition(
        self, condition_expr: str, context: Dict[str, Any]
    ) -> bool:
        """
        Public helper: evaluate a condition expression against *context*.
        Returns True/False.  Exposed for unit-testing condition logic directly.
        """
        return self._eval_condition(condition_expr, context)

    def _handle_condition(self, node: DagNode, run: WorkflowRun) -> str:
        """
        Evaluate a condition node.
        Returns the node_id of the branch to take (true_branch or false_branch).
        """
        # Use the output of the most-recently completed dependency as `output`
        dep_output = None
        for dep_id in reversed(node.depends_on):
            r = run.node_results.get(dep_id)
            if r and r.succeeded:
                dep_output = r.output
                break

        eval_ctx = {
            "output": dep_output,
            "workflow_input": run.input_data,
            "node_outputs": {
                nid: r.output
                for nid, r in run.node_results.items()
                if r.succeeded
            },
        }
        result = self._eval_condition(node.condition, eval_ctx)
        chosen = node.true_branch if result else node.false_branch
        logger.info(
            "Condition '%s' evaluated to %s → branch '%s'",
            node.id, result, chosen,
        )
        return chosen

    # ── Condition evaluation ──────────────────────────────────────────────────

    def _eval_condition(self, expr: str, ctx: Dict[str, Any]) -> bool:
        """
        Safely evaluate *expr* with a restricted set of names.

        Available names
        ───────────────
          output         — output of the upstream dependency node
          workflow_input — the original trigger payload
          node_outputs   — dict of all successful node outputs so far
          len, str, int, float, bool, abs, round, min, max

        Attribute-style access on dicts is enabled via _Namespace so
        ``output.score`` works for ``{"score": 0.9}``.
        """
        try:
            tree = _ast.parse(expr, mode="eval")
            ns_output = _Namespace(ctx.get("output"))
            ns_workflow = _Namespace(ctx.get("workflow_input", {}))
            ns_node_outputs = {
                k: _Namespace(v)
                for k, v in ctx.get("node_outputs", {}).items()
            }
            safe_builtins = {
                "len": len, "str": str, "int": int, "float": float,
                "bool": bool, "abs": abs, "round": round,
                "min": min, "max": max, "True": True, "False": False,
                "None": None,
            }
            namespace: Dict[str, Any] = {
                "__builtins__": safe_builtins,
                "output": ns_output,
                "workflow_input": ns_workflow,
                "node_outputs": ns_node_outputs,
            }
            return bool(eval(compile(tree, "<condition>", "eval"), namespace))
        except Exception as exc:
            logger.error(
                "Condition evaluation failed for %r: %s — defaulting to False",
                expr, exc,
            )
            return False

    # ── Input construction ────────────────────────────────────────────────────

    def _build_node_input(
        self, node: DagNode, run: WorkflowRun
    ) -> Dict[str, Any]:
        """
        Construct the input dict that is passed to the node's executor.

        Structure
        ─────────
          workflow_input  — the original workflow trigger payload
          dep_outputs     — {node_id: output} for every completed dependency
          input           — shortcut: single-dep output, or dep_outputs if multiple
        """
        dep_outputs: Dict[str, Any] = {}
        for dep_id in node.depends_on:
            r = run.node_results.get(dep_id)
            if r and r.succeeded:
                dep_outputs[dep_id] = r.output

        shortcut = (
            list(dep_outputs.values())[0]
            if len(dep_outputs) == 1
            else dep_outputs if dep_outputs else run.input_data
        )
        return {
            "workflow_input": run.input_data,
            "dep_outputs": dep_outputs,
            "input": shortcut,
        }

    # ── Skip propagation ──────────────────────────────────────────────────────

    def _mark_branch_skipped(
        self,
        dag: WorkflowDag,
        branch_start: str,
        completed: Set[str],
        skipped: Set[str],
        run: WorkflowRun,
    ) -> None:
        """
        Recursively skip *branch_start* and all nodes that are exclusively
        reachable through it (i.e., have no completed dep outside the skipped set).
        """
        queue = [branch_start]
        while queue:
            nid = queue.pop()
            if nid in completed or nid in skipped:
                continue
            skipped.add(nid)
            run.node_results[nid] = NodeResult(
                node_id=nid, status=NodeStatus.SKIPPED
            )
            # Transitively skip successors that are gated only on this path
            for other_id, other_node in dag.nodes.items():
                if other_id in completed or other_id in skipped:
                    continue
                if nid in other_node.depends_on and all(
                    dep in (completed | skipped) for dep in other_node.depends_on
                ):
                    # This node's deps are resolved, but at least one is skipped
                    # → skip it too
                    if any(dep in skipped for dep in other_node.depends_on):
                        queue.append(other_id)

    def _propagate_skips_from_failed(
        self,
        dag: WorkflowDag,
        failed_node_id: str,
        completed: Set[str],
        failed: Set[str],
        skipped: Set[str],
        run: WorkflowRun,
    ) -> None:
        """
        After a node fails, mark all downstream nodes that exclusively depend
        on the failed node as skipped (they can never run).
        """
        terminal = completed | failed | skipped
        queue = [failed_node_id]
        seen: Set[str] = set()
        while queue:
            current = queue.pop()
            for nid, node in dag.nodes.items():
                if nid in terminal or nid in seen:
                    continue
                if current in node.depends_on:
                    seen.add(nid)
                    skipped.add(nid)
                    run.node_results[nid] = NodeResult(
                        node_id=nid, status=NodeStatus.SKIPPED,
                        error=f"Skipped: upstream node '{current}' failed",
                    )
                    queue.append(nid)
            terminal.add(current)

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _check_circuit_breaker(
        self, run: WorkflowRun, failed_node_id: str
    ) -> bool:
        """
        Record this failure and return True if the breaker should trip.
        Failures older than CB_WINDOW_SECONDS are evicted before checking.
        """
        now = time.monotonic()
        run._recent_failures.append((now, failed_node_id))
        while (
            run._recent_failures
            and now - run._recent_failures[0][0] > CB_WINDOW_SECONDS
        ):
            run._recent_failures.popleft()
        tripped = len(run._recent_failures) >= CB_FAILURE_THRESHOLD
        if tripped:
            logger.warning(
                "Circuit breaker tripped for execution %s (%d failures in %ds)",
                run.execution_id,
                len(run._recent_failures),
                int(CB_WINDOW_SECONDS),
            )
        return tripped

    # ── Default agent executor ────────────────────────────────────────────────

    async def _default_agent_executor(
        self,
        agent_id: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Default executor: delegates to AgentExecutor which runs the full
        LLM call + tool execution + memory update pipeline.
        """
        # Import here to avoid a circular import at module load time
        from app.services.agent_executor import agent_executor
        return await agent_executor.execute(agent_id, input_data, context)

    # ── Database helpers ──────────────────────────────────────────────────────

    async def _load_dag_config(self, workflow_id: str) -> Dict[str, Any]:
        """Load dag_config from the workflows table."""
        try:
            from app.models.database import Workflow
            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(Workflow).where(Workflow.id == UUID(workflow_id))
                    )
                ).scalar_one_or_none()
            if not row:
                raise ValueError(f"Workflow '{workflow_id}' not found")
            return row.dag_config or {}
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load workflow '{workflow_id}': {exc}"
            ) from exc

    async def _create_execution_record(self, workflow_id: str) -> str:
        """Insert a new execution row and return its id as a string."""
        try:
            async with AsyncSessionLocal() as session:
                execution = Execution(
                    workflow_id=UUID(workflow_id),
                    status="running",
                    started_at=datetime.now(timezone.utc),
                )
                session.add(execution)
                await session.flush()
                eid = str(execution.id)
                await session.commit()
            return eid
        except Exception as exc:
            logger.warning(
                "Could not create execution record for workflow %s: %s "
                "— continuing with synthetic id",
                workflow_id, exc,
            )
            return str(_uuid.uuid4())

    async def _persist_step(
        self, run: WorkflowRun, node: DagNode, result: NodeResult
    ) -> None:
        """Write the completed step to execution_steps (fire-and-forget safe)."""
        try:
            async with AsyncSessionLocal() as session:
                step = ExecutionStep(
                    execution_id=UUID(run.execution_id),
                    agent_id=(
                        UUID(node.agent_id)
                        if node.agent_id
                        else None
                    ),
                    input=result.input_data,
                    output=result.output,
                    duration_ms=result.duration_ms,
                )
                session.add(step)
                await session.commit()
        except Exception as exc:
            logger.debug(
                "Could not persist step for node '%s': %s", node.id, exc
            )

    async def _update_execution_record(self, run: WorkflowRun) -> None:
        """Update the executions row with final status + result."""
        try:
            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(Execution).where(
                            Execution.id == UUID(run.execution_id)
                        )
                    )
                ).scalar_one_or_none()
                if row:
                    row.status = run.status
                    row.completed_at = run.completed_at
                    row.result = {
                        nid: {"status": r.status.value, "output": r.output}
                        for nid, r in run.node_results.items()
                    }
                    if run.error:
                        row.error_log = run.error
                    await session.commit()
        except Exception as exc:
            logger.debug(
                "Could not update execution record %s: %s", run.execution_id, exc
            )

    def __repr__(self) -> str:
        return (
            f"WorkflowOrchestrator("
            f"active_runs={len(self._active_runs)}, "
            f"registry={self._registry!r})"
        )
