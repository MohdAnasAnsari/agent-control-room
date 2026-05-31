"""
Agent State Manager
════════════════════════════════════════════════════════════════════════════════
In-memory agent state with asynchronous PostgreSQL persistence.

Architecture
────────────
Each AgentState is a dataclass that owns its asyncio.Lock.  All mutation
methods are synchronous (lock is exposed for callers that need atomicity
across multiple mutations); persistence is fully async.

DB writes use PostgreSQL upsert (INSERT … ON CONFLICT DO UPDATE) so they
are safe to retry and order-independent.  On failure, exponential back-off
is applied up to _MAX_RETRIES times; execution continues on in-memory state
if all attempts fail so a DB outage never blocks agents.

AgentContext tracks the full execution path and per-step I/O for a single
workflow run, with its own upsert persistence.
"""

import asyncio
import logging
import uuid as _uuid_module
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.database import Agent, AgentContextRecord, AgentStateRecord
from app.models.db_session import AsyncSessionLocal

logger = logging.getLogger(__name__)

MAX_MEMORY_MESSAGES: int = 20
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 0.5  # seconds; doubled on each attempt


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════════════════════


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


# ══════════════════════════════════════════════════════════════════════════════
# Low-level DB helpers  (module-level so they can be patched in tests)
# ══════════════════════════════════════════════════════════════════════════════


async def _upsert_agent_state(session: Any, state: "AgentState") -> None:
    """INSERT or UPDATE the agent_states row that corresponds to *state*."""
    now = datetime.now(timezone.utc)
    agent_uuid = UUID(state.agent_id)

    stmt = (
        pg_insert(AgentStateRecord)
        .values(
            id=_uuid_module.uuid4(),
            agent_id=agent_uuid,
            tools=state.tools,
            memory=state.memory,
            runtime_status=state.status.value,
            current_task=state.current_task,
            execution_count=state.execution_count,
            last_execution=state.last_execution,
            extra_metadata=state.metadata,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_agent_states_agent_id",
            set_={
                "tools": state.tools,
                "memory": state.memory,
                "runtime_status": state.status.value,
                "current_task": state.current_task,
                "execution_count": state.execution_count,
                "last_execution": state.last_execution,
                "extra_metadata": state.metadata,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)


async def _upsert_agent_context(session: Any, ctx: "AgentContext") -> None:
    """INSERT or UPDATE the agent_contexts row for *ctx*."""
    now = datetime.now(timezone.utc)
    exec_uuid = UUID(ctx.execution_id)
    wf_uuid = UUID(ctx.workflow_id) if ctx.workflow_id else None
    parent_uuid = UUID(ctx.parent_agent_id) if ctx.parent_agent_id else None

    stmt = (
        pg_insert(AgentContextRecord)
        .values(
            id=_uuid_module.uuid4(),
            execution_id=exec_uuid,
            workflow_id=wf_uuid,
            parent_agent_id=parent_uuid,
            dependencies=ctx.dependencies,
            execution_path=ctx.execution_path,
            step_data=ctx.step_data,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_agent_contexts_execution_id",
            set_={
                "workflow_id": wf_uuid,
                "parent_agent_id": parent_uuid,
                "dependencies": ctx.dependencies,
                "execution_path": ctx.execution_path,
                "step_data": ctx.step_data,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)


async def _fetch_agent_state(session: Any, agent_id: str) -> Optional["AgentState"]:
    """Load AgentState by joining agents + agent_states.  Returns None if missing."""
    agent_uuid = UUID(agent_id)

    agent_row = (
        await session.execute(select(Agent).where(Agent.id == agent_uuid))
    ).scalar_one_or_none()
    if agent_row is None:
        return None

    state_row = (
        await session.execute(
            select(AgentStateRecord).where(AgentStateRecord.agent_id == agent_uuid)
        )
    ).scalar_one_or_none()

    base_kwargs: Dict[str, Any] = dict(
        agent_id=str(agent_row.id),
        name=agent_row.name,
        role=agent_row.role,
        system_prompt=agent_row.system_prompt,
        model=getattr(agent_row, "model", "claude-sonnet-4-6") or "claude-sonnet-4-6",
    )
    if state_row:
        return AgentState(
            **base_kwargs,
            tools=state_row.tools or [],
            memory=state_row.memory or [],
            status=AgentStatus(state_row.runtime_status),
            current_task=state_row.current_task,
            execution_count=state_row.execution_count or 0,
            last_execution=state_row.last_execution,
            metadata=state_row.extra_metadata or {},
        )
    return AgentState(**base_kwargs)


async def load_all_states_from_db() -> List["AgentState"]:
    """
    Load every agent and its optional state record in a single query.
    Used by AgentRegistry at startup.  Returns [] on DB error (graceful
    degradation — the registry starts empty and fills on first registration).
    """
    try:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(Agent, AgentStateRecord).outerjoin(
                        AgentStateRecord, Agent.id == AgentStateRecord.agent_id
                    )
                )
            ).all()
    except Exception as exc:
        logger.error("load_all_states_from_db failed: %s", exc)
        return []

    states: List["AgentState"] = []
    for agent_row, state_row in rows:
        base_kwargs: Dict[str, Any] = dict(
            agent_id=str(agent_row.id),
            name=agent_row.name,
            role=agent_row.role,
            system_prompt=agent_row.system_prompt,
            model=getattr(agent_row, "model", "claude-sonnet-4-6") or "claude-sonnet-4-6",
        )
        if state_row:
            s = AgentState(
                **base_kwargs,
                tools=state_row.tools or [],
                memory=state_row.memory or [],
                status=AgentStatus(state_row.runtime_status),
                current_task=state_row.current_task,
                execution_count=state_row.execution_count or 0,
                last_execution=state_row.last_execution,
                metadata=state_row.extra_metadata or {},
            )
        else:
            s = AgentState(**base_kwargs)
        states.append(s)

    logger.info("Loaded %d agent states from DB", len(states))
    return states


# ══════════════════════════════════════════════════════════════════════════════
# AgentState
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class AgentState:
    """
    In-memory representation of a live agent.

    Non-dataclass instance attributes (set in __post_init__):
      _dirty  — True when in-memory state differs from last DB write
      _lock   — asyncio.Lock for per-agent mutual exclusion
    """

    agent_id: str
    name: str
    role: str
    system_prompt: str
    model: str = "claude-sonnet-4-6"
    tools: List[str] = field(default_factory=list)
    memory: List[Dict[str, Any]] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    execution_count: int = 0
    last_execution: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._dirty: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Memory management ────────────────────────────────────────────────────

    def update_memory(self, content: str, role: str) -> None:
        """
        Append a message to conversation history.
        role must be 'user', 'assistant', or 'system'.
        Memory is trimmed automatically after appending.
        """
        self.memory.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._dirty = True
        self.clear_old_memory()

    def clear_old_memory(self, keep_last: int = MAX_MEMORY_MESSAGES) -> None:
        """Trim conversation history to *keep_last* most-recent messages."""
        if len(self.memory) > keep_last:
            self.memory = self.memory[-keep_last:]
            self._dirty = True

    # ── Status & execution tracking ──────────────────────────────────────────

    def set_status(self, new_status: AgentStatus) -> None:
        """Update runtime status.  Marks dirty for all transitions."""
        self.status = new_status
        self._dirty = True

    def increment_execution(self) -> None:
        """Increment run counter and stamp last_execution.  Call at task start."""
        self.execution_count += 1
        self.last_execution = datetime.now(timezone.utc)
        self._dirty = True

    def set_task(self, task: Optional[str]) -> None:
        self.current_task = task
        self._dirty = True

    def add_tool(self, tool_name: str) -> None:
        if tool_name not in self.tools:
            self.tools.append(tool_name)
            self._dirty = True

    def remove_tool(self, tool_name: str) -> None:
        if tool_name in self.tools:
            self.tools.remove(tool_name)
            self._dirty = True

    def update_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self._dirty = True

    # ── Persistence ──────────────────────────────────────────────────────────

    async def save_to_db(self) -> bool:
        """
        Persist the current state to PostgreSQL using upsert.

        Retries up to _MAX_RETRIES times with exponential back-off.
        On total failure: logs the error, returns False, preserves in-memory
        state — agent execution is never blocked by a DB outage.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with AsyncSessionLocal() as session:
                    await _upsert_agent_state(session, self)
                    await session.commit()
                self._dirty = False
                logger.debug("Saved agent %s to DB", self.agent_id)
                return True
            except Exception as exc:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "DB write failed for agent %s (attempt %d/%d): %s "
                        "— retrying in %.1fs",
                        self.agent_id,
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d DB write attempts failed for agent %s: %s "
                        "— continuing with in-memory state.",
                        _MAX_RETRIES,
                        self.agent_id,
                        exc,
                    )
        return False

    @classmethod
    async def load_from_db(cls, agent_id: str) -> Optional["AgentState"]:
        """
        Retrieve and reconstruct an AgentState from the database.
        Returns None if the agent_id does not exist or on DB error.
        """
        try:
            async with AsyncSessionLocal() as session:
                return await _fetch_agent_state(session, agent_id)
        except Exception as exc:
            logger.error("Failed to load agent %s from DB: %s", agent_id, exc)
            return None

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "tools": list(self.tools),
            "memory": list(self.memory),
            "status": self.status.value,
            "current_task": self.current_task,
            "execution_count": self.execution_count,
            "last_execution": (
                self.last_execution.isoformat() if self.last_execution else None
            ),
            "metadata": dict(self.metadata),
        }

    def __repr__(self) -> str:
        return (
            f"AgentState(id={self.agent_id!r}, name={self.name!r}, "
            f"status={self.status.value!r}, executions={self.execution_count})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# AgentContext
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class AgentContext:
    """
    Execution context for a single workflow run.

    Tracks:
      - Which workflow and parent agent triggered this execution
      - The ordered list of agent IDs that ran (execution_path)
      - Per-step I/O, duration, and timestamps (step_data)

    Non-dataclass instance attributes (set in __post_init__):
      execution_path — List[str] of agent_ids in run order
      step_data      — Dict[agent_id, step-detail-dict]
      _lock          — asyncio.Lock for concurrent step updates
    """

    execution_id: str
    workflow_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.execution_path: List[str] = []
        self.step_data: Dict[str, Dict[str, Any]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Context mutations ────────────────────────────────────────────────────

    def add_to_context(
        self,
        agent_id: str,
        input_data: Any,
        output_data: Any = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Register a step in the execution path.  Safe to call multiple times."""
        if agent_id not in self.execution_path:
            self.execution_path.append(agent_id)
        self.step_data[agent_id] = {
            "input": input_data,
            "output": output_data,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def update_step_output(
        self,
        agent_id: str,
        output_data: Any,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Patch the output + duration for an already-registered step."""
        if agent_id in self.step_data:
            self.step_data[agent_id]["output"] = output_data
            if duration_ms is not None:
                self.step_data[agent_id]["duration_ms"] = duration_ms

    def get_full_context(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the complete execution context."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "parent_agent_id": self.parent_agent_id,
            "dependencies": list(self.dependencies),
            "execution_path": list(self.execution_path),
            "step_count": len(self.execution_path),
            "steps": {k: dict(v) for k, v in self.step_data.items()},
        }

    def get_step(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self.step_data.get(agent_id)

    def reset(self) -> None:
        """Clear execution state so the context can be reused for a new run."""
        self.execution_path.clear()
        self.step_data.clear()

    # ── Persistence ──────────────────────────────────────────────────────────

    async def save_to_db(self) -> bool:
        """
        Upsert this context to agent_contexts.
        Retries with exponential back-off; returns False on total failure.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                async with AsyncSessionLocal() as session:
                    await _upsert_agent_context(session, self)
                    await session.commit()
                return True
            except Exception as exc:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "AgentContext DB write failed (exec %s, attempt %d/%d): %s "
                        "— retrying in %.1fs",
                        self.execution_id,
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d AgentContext write attempts failed for exec %s: %s",
                        _MAX_RETRIES,
                        self.execution_id,
                        exc,
                    )
        return False

    @classmethod
    async def load_from_db(cls, execution_id: str) -> Optional["AgentContext"]:
        """Reconstruct an AgentContext from the database.  Returns None if missing."""
        try:
            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(AgentContextRecord).where(
                            AgentContextRecord.execution_id == UUID(execution_id)
                        )
                    )
                ).scalar_one_or_none()
            if row is None:
                return None
            ctx = cls(
                execution_id=execution_id,
                workflow_id=str(row.workflow_id) if row.workflow_id else None,
                parent_agent_id=(
                    str(row.parent_agent_id) if row.parent_agent_id else None
                ),
                dependencies=row.dependencies or [],
            )
            ctx.execution_path = row.execution_path or []
            ctx.step_data = row.step_data or {}
            return ctx
        except Exception as exc:
            logger.error(
                "Failed to load AgentContext %s from DB: %s", execution_id, exc
            )
            return None

    def __repr__(self) -> str:
        return (
            f"AgentContext(execution_id={self.execution_id!r}, "
            f"steps={len(self.execution_path)}, "
            f"path={self.execution_path!r})"
        )
