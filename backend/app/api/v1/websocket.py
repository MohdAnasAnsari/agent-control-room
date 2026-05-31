"""
WebSocket endpoint — /ws/executions/{execution_id}
════════════════════════════════════════════════════════════════════════════════
Provides real-time execution monitoring by:
  1. Accepting a WebSocket connection for an execution_id
  2. Checking the orchestrator's active_runs for live node updates
  3. Falling back to DB polling when the execution is not in active_runs
  4. Sending WSMessage-shaped JSON frames matching the frontend types
  5. Closing gracefully when the execution reaches a terminal state

Message types emitted:
  • node_status   — when a DAG node starts/completes/fails
  • log           — informational log lines
  • metrics_update— aggregated metrics delta
  • execution_complete — final success state
  • execution_error    — final failure state
  • ping           — keepalive every 15s

Frontend WSMessage shape (matches src/types/index.ts):
  {
    type: 'node_status' | 'log' | 'metrics_update' | 'execution_complete' | 'execution_error' | 'ping'
    executionId: string
    nodeStatus?: {nodeId, status, startedAt?, completedAt?, durationMs?, output?, error?}
    log?: {id, timestamp, level, nodeId, nodeName, message, data?}
    metrics?: {nodesTotal, nodesCompleted, nodesFailed, totalDurationMs, tokensUsed, ...}
    error?: string
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.models.database import Execution, ExecutionStep
from app.models.db_session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_TERMINAL = {"completed", "failed", "halted", "stopped", "deleted"}
_POLL_INTERVAL_S = 1.0
_PING_INTERVAL_S = 15.0
_MAX_DURATION_S = 600  # 10-minute hard limit per connection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _frame(msg_type: str, execution_id: str, **kwargs) -> str:
    return json.dumps({"type": msg_type, "executionId": execution_id, **kwargs})


async def _get_execution(execution_id: UUID) -> Optional[Execution]:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Execution).where(Execution.id == execution_id)
            )
            return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("ws: DB error fetching execution %s: %s", execution_id, exc)
        return None


async def _get_steps(execution_id: UUID) -> list[ExecutionStep]:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ExecutionStep)
                .where(ExecutionStep.execution_id == execution_id)
                .order_by(ExecutionStep.timestamp)
            )
            return list(result.scalars().all())
    except Exception:
        return []


def _step_to_node_status(step: ExecutionStep) -> dict:
    return {
        "nodeId": str(step.id),
        "status": "completed" if step.output else "pending",
        "startedAt": step.timestamp.isoformat() if step.timestamp else None,
        "completedAt": step.timestamp.isoformat() if step.output else None,
        "durationMs": step.duration_ms,
        "output": step.output,
        "error": None,
    }


def _step_to_log(step: ExecutionStep, execution_id: str) -> dict:
    output = step.output or {}
    agent_name = output.get("agent_name", f"agent-{str(step.agent_id or 'unknown')[:8]}")
    return {
        "id": str(uuid.uuid4()),
        "timestamp": step.timestamp.isoformat() if step.timestamp else datetime.now(timezone.utc).isoformat(),
        "level": "error" if not step.output else "info",
        "nodeId": str(step.id),
        "nodeName": str(agent_name),
        "message": f"Step completed in {step.duration_ms}ms" if step.output else "Step pending",
        "data": step.output,
    }


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/executions/{execution_id}")
async def ws_execution(websocket: WebSocket, execution_id: UUID):
    """
    WebSocket handler for real-time execution monitoring.

    The frontend connects here immediately after triggering a workflow execution.
    Updates are sent as JSON frames until the execution reaches a terminal state
    or the client disconnects.
    """
    await websocket.accept()
    eid_str = str(execution_id)
    logger.info("ws: client connected for execution %s", eid_str)

    sent_step_ids: set[str] = set()
    elapsed = 0.0
    ping_elapsed = 0.0

    try:
        # ── Initial state ──────────────────────────────────────────────────────
        execution = await _get_execution(execution_id)
        if not execution:
            await websocket.send_text(_frame(
                "execution_error", eid_str,
                error=f"Execution '{eid_str}' not found"
            ))
            await websocket.close(code=1008)
            return

        # Emit current status
        await websocket.send_text(_frame(
            "log", eid_str,
            log={
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "info",
                "nodeId": "system",
                "nodeName": "orchestrator",
                "message": f"Connected — execution status: {execution.status}",
            }
        ))

        # If already terminal, emit final state and close
        if execution.status in _TERMINAL:
            await _emit_terminal(websocket, execution, eid_str)
            return

        # ── Polling loop ───────────────────────────────────────────────────────
        while elapsed < _MAX_DURATION_S:
            await asyncio.sleep(_POLL_INTERVAL_S)
            elapsed += _POLL_INTERVAL_S
            ping_elapsed += _POLL_INTERVAL_S

            # Keepalive ping
            if ping_elapsed >= _PING_INTERVAL_S:
                await websocket.send_text(_frame("ping", eid_str))
                ping_elapsed = 0.0

            # Check for new steps
            steps = await _get_steps(execution_id)
            for step in steps:
                sid = str(step.id)
                if sid in sent_step_ids:
                    continue
                sent_step_ids.add(sid)

                # Emit node_status
                await websocket.send_text(_frame(
                    "node_status", eid_str,
                    nodeStatus=_step_to_node_status(step),
                ))
                # Emit log
                await websocket.send_text(_frame(
                    "log", eid_str,
                    log=_step_to_log(step, eid_str),
                ))

            # Emit metrics delta
            completed = sum(1 for s in steps if s.output)
            failed = sum(1 for s in steps if not s.output and s.timestamp < datetime.now(timezone.utc))
            await websocket.send_text(_frame(
                "metrics_update", eid_str,
                metrics={
                    "nodesTotal": len(steps),
                    "nodesCompleted": completed,
                    "nodesFailed": 0,
                    "totalDurationMs": int(elapsed * 1000),
                    "tokensUsed": 0,
                    "estimatedCostUsd": 0.0,
                    "currentNodeLabel": None,
                    "successRate": (completed / len(steps) if steps else 0.0),
                }
            ))

            # Poll execution status
            execution = await _get_execution(execution_id)
            if not execution:
                break

            if execution.status in _TERMINAL:
                await _emit_terminal(websocket, execution, eid_str)
                return

        # Timeout
        await websocket.send_text(_frame(
            "execution_error", eid_str,
            error=f"WebSocket stream timed out after {_MAX_DURATION_S}s"
        ))

    except WebSocketDisconnect:
        logger.info("ws: client disconnected from execution %s", eid_str)
    except Exception as exc:
        logger.error("ws: error in execution %s stream: %s", eid_str, exc)
        try:
            await websocket.send_text(_frame("execution_error", eid_str, error=str(exc)))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _emit_terminal(websocket: WebSocket, execution: Execution, eid_str: str) -> None:
    """Emit the final execution_complete or execution_error frame and close."""
    if execution.status == "completed":
        await websocket.send_text(_frame(
            "execution_complete", eid_str,
            result=execution.result,
            completedAt=execution.completed_at.isoformat() if execution.completed_at else None,
        ))
    else:
        await websocket.send_text(_frame(
            "execution_error", eid_str,
            error=execution.error_log or f"Execution {execution.status}",
        ))
    await websocket.close(code=1000)
