"""
Agent Registry
════════════════════════════════════════════════════════════════════════════════
Central in-memory store for all live AgentState objects.

Concurrency model
─────────────────
A single asyncio.Lock (_lock) serialises all mutations to _agents and
_dirty_agents.  The lock is acquired briefly for dict operations only —
slow DB I/O always runs outside the lock so a stuck DB write never blocks
other coroutines from reading or updating the registry.

Persistence model
─────────────────
  • Startup   — start() loads all persisted agents from DB into memory.
  • Batch     — _batch_sync_loop() flushes dirty agents every
                BATCH_SYNC_INTERVAL_S seconds (default 2).
  • Critical  — mark_critical(agent_id) triggers an immediate awaited save
                for error states or other high-priority changes.
  • Shutdown  — stop() cancels the batch loop and flushes all dirty states.

Usage
─────
    from app.services.agent_registry import registry

    # app startup
    await registry.start()

    # app shutdown
    await registry.stop()

    # typical service call
    agent = await registry.get_agent(some_id)
    agent.set_status(AgentStatus.RUNNING)
    await registry.mark_dirty(some_id)        # picked up within 2 s
    # -or- for immediate persistence:
    await registry.mark_critical(some_id)
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set

from app.services.agent_state_manager import AgentState, load_all_states_from_db

logger = logging.getLogger(__name__)

BATCH_SYNC_INTERVAL_S: float = 2.0


class AgentRegistry:
    """Thread-safe central store for AgentState objects."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentState] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._dirty_agents: Set[str] = set()
        self._sync_task: Optional[asyncio.Task] = None
        self._running: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Load all persisted agents from the DB and launch the background
        batch-sync loop.  Idempotent — safe to call more than once.
        """
        if self._running:
            return
        self._running = True
        await self._load_all_from_db()
        self._sync_task = asyncio.create_task(
            self._batch_sync_loop(), name="agent-registry-batch-sync"
        )
        logger.info(
            "AgentRegistry started — %d agents loaded from DB", len(self._agents)
        )

    async def stop(self) -> None:
        """
        Cancel the batch-sync loop and flush all remaining dirty states.
        Call during application shutdown.
        """
        self._running = False
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        await self.sync_to_db()
        logger.info("AgentRegistry stopped — dirty states flushed")

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def register_agent(self, state: AgentState) -> None:
        """
        Add or replace an agent in the registry and mark it dirty so it
        will be persisted within the next batch window.
        """
        async with self._lock:
            self._agents[state.agent_id] = state
            self._dirty_agents.add(state.agent_id)

    async def get_agent(self, agent_id: str) -> Optional[AgentState]:
        """Return the AgentState for *agent_id*, or None if not registered."""
        async with self._lock:
            return self._agents.get(agent_id)

    async def get_or_load(self, agent_id: str) -> Optional[AgentState]:
        """
        Return the in-memory state if registered; otherwise attempt to load
        it from the DB and register it.  Returns None if not found anywhere.
        """
        async with self._lock:
            if agent_id in self._agents:
                return self._agents[agent_id]

        state = await AgentState.load_from_db(agent_id)
        if state:
            await self.register_agent(state)
        return state

    async def list_all_agents(self) -> List[AgentState]:
        """Return a snapshot list of all currently registered agents."""
        async with self._lock:
            return list(self._agents.values())

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Remove an agent from the in-memory registry.
        Returns True if the agent was present, False otherwise.
        The corresponding DB row is NOT deleted — use the agent service for that.
        """
        async with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            self._dirty_agents.discard(agent_id)
        return True

    async def mark_dirty(self, agent_id: str) -> None:
        """
        Explicitly enqueue an agent for the next batch DB sync.
        Call after any out-of-band mutation not captured by AgentState methods.
        """
        async with self._lock:
            if agent_id in self._agents:
                self._dirty_agents.add(agent_id)

    # ── Persistence ──────────────────────────────────────────────────────────

    async def sync_to_db(self) -> Dict[str, bool]:
        """
        Persist all currently dirty agents.

        The global lock is held only to snapshot the dirty set and to update
        it afterwards — DB I/O runs concurrently outside the lock.

        Returns a mapping of {agent_id: success_bool}.
        """
        async with self._lock:
            to_sync = list(self._dirty_agents)

        if not to_sync:
            return {}

        # Collect actual AgentState objects (agents may have been unregistered
        # between the snapshot and now)
        agents_to_save: List[AgentState] = []
        async with self._lock:
            for aid in to_sync:
                agent = self._agents.get(aid)
                if agent:
                    agents_to_save.append(agent)

        results = await asyncio.gather(
            *(a.save_to_db() for a in agents_to_save),
            return_exceptions=True,
        )

        outcome: Dict[str, bool] = {}
        async with self._lock:
            for agent, result in zip(agents_to_save, results):
                success = result is True
                outcome[agent.agent_id] = success
                if success:
                    self._dirty_agents.discard(agent.agent_id)

        failed = [aid for aid, ok in outcome.items() if not ok]
        if failed:
            logger.warning(
                "Batch sync: %d agent(s) failed to persist: %s", len(failed), failed
            )

        return outcome

    async def mark_critical(self, agent_id: str) -> bool:
        """
        Immediately persist a single agent's state, bypassing the 2-second
        batch window.  Use after ERROR transitions or other priority changes.
        Returns True on success.
        """
        async with self._lock:
            agent = self._agents.get(agent_id)
        if not agent:
            logger.warning("mark_critical called for unregistered agent %s", agent_id)
            return False

        success = await agent.save_to_db()
        if success:
            async with self._lock:
                self._dirty_agents.discard(agent_id)
        return success

    # ── Stats / introspection ────────────────────────────────────────────────

    def agent_count(self) -> int:
        """Best-effort agent count (no lock — suitable for metrics/logging)."""
        return len(self._agents)

    def dirty_count(self) -> int:
        """Number of agents currently pending a DB write."""
        return len(self._dirty_agents)

    async def status_summary(self) -> Dict[str, int]:
        """
        Return a count breakdown by AgentStatus value.
        Useful for health dashboards.
        """
        from collections import Counter
        async with self._lock:
            statuses = [a.status.value for a in self._agents.values()]
        return dict(Counter(statuses))

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _load_all_from_db(self) -> None:
        """Populate the registry from the DB.  Errors are logged, not raised."""
        states = await load_all_states_from_db()
        async with self._lock:
            for state in states:
                self._agents[state.agent_id] = state

    async def _batch_sync_loop(self) -> None:
        """
        Background coroutine that persists dirty agents every
        BATCH_SYNC_INTERVAL_S seconds.  Runs until self._running is False.
        """
        while self._running:
            await asyncio.sleep(BATCH_SYNC_INTERVAL_S)
            try:
                outcome = await self.sync_to_db()
                if outcome:
                    saved = sum(1 for ok in outcome.values() if ok)
                    logger.debug(
                        "Batch sync: %d/%d agents persisted",
                        saved,
                        len(outcome),
                    )
            except Exception as exc:
                logger.error("Unexpected error in batch sync loop: %s", exc)

    def __repr__(self) -> str:
        return (
            f"AgentRegistry(agents={self.agent_count()}, "
            f"dirty={self.dirty_count()}, running={self._running})"
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Import this in services and API handlers:
#   from app.services.agent_registry import registry
registry = AgentRegistry()
