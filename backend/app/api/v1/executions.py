"""
Execution endpoints — /api/v1/executions
"""

import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import not_found
from app.models.database import User
from app.models.db_session import get_db
from app.models.schemas import (
    ExecutionDetail,
    ExecutionOut,
    ExecutionStepOut,
    PaginatedResponse,
)
from app.services import workflow_service

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get(
    "",
    response_model=PaginatedResponse[ExecutionOut],
    summary="List executions with optional filters",
)
async def list_executions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    workflow_id: Optional[UUID] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    total, items = await workflow_service.list_executions(
        db, skip=skip, limit=limit, status=status_filter, workflow_id=workflow_id
    )
    has_more = (skip + limit) < total
    response = JSONResponse(
        content=PaginatedResponse[ExecutionOut](
            total=total,
            items=[ExecutionOut.model_validate(e).model_dump(mode="json") for e in items],
            has_more=has_more,
        ).model_dump(mode="json")
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(skip // limit + 1 if limit else 1)
    response.headers["Cache-Control"] = "max-age=300"
    return response


@router.get(
    "/{execution_id}",
    response_model=ExecutionDetail,
    summary="Get execution details including steps",
    responses={404: {"description": "Execution not found"}},
)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    execution = await workflow_service.get_execution(db, execution_id)
    if not execution:
        raise not_found("Execution")
    steps = await workflow_service.get_execution_steps(db, execution_id)
    result = ExecutionDetail.model_validate(execution)
    result.steps = [ExecutionStepOut.model_validate(s) for s in steps]
    return result


@router.get(
    "/{execution_id}/logs",
    summary="Stream execution logs as NDJSON",
    responses={
        200: {"content": {"application/x-ndjson": {}}, "description": "Streamed log lines"},
        404: {"description": "Execution not found"},
    },
)
async def stream_execution_logs(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    execution = await workflow_service.get_execution(db, execution_id)
    if not execution:
        raise not_found("Execution")

    steps = await workflow_service.get_execution_steps(db, execution_id)

    async def _generate():
        # Emit execution header
        header = {
            "event": "execution_start",
            "execution_id": str(execution_id),
            "workflow_id": str(execution.workflow_id),
            "status": execution.status,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
        }
        yield json.dumps(header) + "\n"

        for step in steps:
            log_line = {
                "event": "step",
                "agent_id": str(step.agent_id) if step.agent_id else None,
                "input": step.input,
                "output": step.output,
                "duration_ms": step.duration_ms,
                "timestamp": step.timestamp.isoformat(),
            }
            yield json.dumps(log_line) + "\n"

        # Emit execution footer
        footer = {
            "event": "execution_end",
            "status": execution.status,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "error": execution.error_log,
        }
        yield json.dumps(footer) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"X-Execution-ID": str(execution_id)},
    )


@router.delete(
    "/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete execution",
    responses={404: {"description": "Execution not found"}},
)
async def delete_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    deleted = await workflow_service.delete_execution(db, execution_id)
    if not deleted:
        raise not_found("Execution")
