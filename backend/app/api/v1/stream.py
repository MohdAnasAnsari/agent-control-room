"""
SSE Streaming endpoints — /api/v1/stream
════════════════════════════════════════════════════════════════════════════════

Two streaming surfaces:

  POST /api/v1/stream/agents/{agent_id}
      Live token-by-token streaming from a single agent call.
      Useful for chat-style interactions without a full workflow.

      SSE event stream:
        data: {"type": "start",  "agent_id": "...", "model": "..."}
        data: {"type": "token",  "content": "Hello"}
        data: {"type": "token",  "content": " world"}
        ...
        data: {"type": "done",   "result": {"output": "...", "model": "...", "cost_usd": ...}}
        data: {"type": "error",  "message": "..."}   # only on failure

  GET  /api/v1/stream/executions/{execution_id}
      Polls the DB and emits SSE events as execution steps complete.
      Ends automatically when the execution reaches a terminal state.

      SSE event stream:
        data: {"type": "status",  "status": "running",   "step_count": 0}
        data: {"type": "step",    "agent_id": "...",      "duration_ms": 1200, "output": {...}}
        ...
        data: {"type": "complete","status": "completed",  "result": {...}}
        data: {"type": "error",   "message": "...",        "status": "failed"}

Format notes
────────────
• Every event is one JSON line followed by two newlines (standard SSE).
• Clients should handle the "error" event and close the connection.
• X-Accel-Buffering: no is set so Nginx does not buffer the stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.models.db_session import get_db
from app.services import workflow_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["streaming"])

_STUB_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


# ── Pydantic request bodies ───────────────────────────────────────────────────

class AgentStreamRequest(BaseModel):
    input: str
    model: Optional[str] = None


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    """Encode one dict as a single SSE data line."""
    return f"data: {json.dumps(event)}\n\n"


_SSE_HEADERS = {
    "Cache-Control":    "no-cache",
    "X-Accel-Buffering": "no",   # disable Nginx proxy buffering
    "Connection":       "keep-alive",
}


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/stream/agents/{agent_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/agents/{agent_id}",
    summary="Stream live token output from a single agent",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE token stream",
        },
        404: {"description": "Agent not found"},
    },
)
async def stream_agent(
    agent_id: UUID,
    payload: AgentStreamRequest,
):
    """
    Start an agent and stream its LLM tokens via Server-Sent Events.

    The endpoint returns the stream immediately; errors mid-stream are
    sent as a final ``{"type": "error"}`` event.
    """
    from app.services.agent_registry import registry
    from app.services.agent_executor import agent_executor

    # Validate agent exists before opening the stream
    agent = await registry.get_or_load(str(agent_id))
    if not agent:
        raise not_found("Agent")

    model = payload.model or agent.model

    async def _generate() -> AsyncIterator[str]:
        full_output = []
        try:
            yield _sse({
                "type": "start",
                "agent_id": str(agent_id),
                "model": model,
            })

            async for chunk in agent_executor.stream(
                str(agent_id),
                payload.input,
                model_override=payload.model,
            ):
                full_output.append(chunk)
                yield _sse({"type": "token", "content": chunk})

            yield _sse({
                "type": "done",
                "result": {
                    "output": "".join(full_output),
                    "model": model,
                },
            })
        except Exception as exc:
            logger.error("stream_agent error for %s: %s", agent_id, exc)
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/stream/executions/{execution_id}
# ══════════════════════════════════════════════════════════════════════════════


_TERMINAL_STATUSES = {"completed", "failed", "halted", "stopped", "deleted"}
_POLL_INTERVAL_S = 1.0   # how often to check for new steps
_STREAM_TIMEOUT_S = 300  # give up after 5 minutes


@router.get(
    "/executions/{execution_id}",
    summary="Stream execution progress as SSE events",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE execution event stream",
        },
        404: {"description": "Execution not found"},
    },
)
async def stream_execution(
    execution_id: UUID,
    poll_interval: float = Query(default=1.0, ge=0.2, le=10.0, description="Poll interval in seconds"),
    db: AsyncSession = Depends(get_db),
):
    """
    Subscribe to live execution progress via Server-Sent Events.

    Polls the database every *poll_interval* seconds (default 1s) and emits
    events as new execution steps are persisted.  The stream ends automatically
    when the execution reaches a terminal state or after 5 minutes.
    """
    execution = await workflow_service.get_execution(db, execution_id)
    if not execution:
        raise not_found("Execution")

    async def _generate() -> AsyncIterator[str]:
        seen_step_ids: set = set()
        elapsed = 0.0

        # Emit current status immediately
        yield _sse({
            "type": "status",
            "execution_id": str(execution_id),
            "status": execution.status,
            "step_count": 0,
        })

        while elapsed < _STREAM_TIMEOUT_S:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Re-open a fresh DB session for each poll (generator holds no session)
            from app.models.db_session import AsyncSessionLocal
            try:
                async with AsyncSessionLocal() as poll_session:
                    current = await workflow_service.get_execution(poll_session, execution_id)
                    if not current:
                        yield _sse({"type": "error", "message": "Execution disappeared"})
                        return

                    steps = await workflow_service.get_execution_steps(poll_session, execution_id)

                    # Emit new steps since last poll
                    new_steps = [s for s in steps if str(s.id) not in seen_step_ids]
                    for step in new_steps:
                        seen_step_ids.add(str(step.id))
                        yield _sse({
                            "type": "step",
                            "step_id": str(step.id),
                            "agent_id": str(step.agent_id) if step.agent_id else None,
                            "duration_ms": step.duration_ms,
                            "output": step.output,
                            "timestamp": step.timestamp.isoformat(),
                        })

                    # Check for terminal state
                    if current.status in _TERMINAL_STATUSES:
                        if current.status == "completed":
                            yield _sse({
                                "type": "complete",
                                "status": current.status,
                                "result": current.result,
                                "completed_at": (
                                    current.completed_at.isoformat()
                                    if current.completed_at else None
                                ),
                            })
                        else:
                            yield _sse({
                                "type": "error",
                                "status": current.status,
                                "message": current.error_log or f"Execution {current.status}",
                            })
                        return

            except Exception as exc:
                logger.warning("stream_execution poll error for %s: %s", execution_id, exc)
                yield _sse({"type": "error", "message": str(exc)})
                return

        # Timeout
        yield _sse({
            "type": "error",
            "message": f"Stream timeout after {_STREAM_TIMEOUT_S}s",
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
