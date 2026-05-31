"""
Workflow endpoints — /api/v1/workflows
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import bad_request, not_found
from app.models.database import User
from app.models.db_session import get_db
from app.models.schemas import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    PaginatedResponse,
    WorkflowCreate,
    WorkflowOut,
    WorkflowUpdate,
)
from app.services import workflow_service
from app.services.dag_models import parse_dag
from app.services.orchestrator import WorkflowOrchestrator
from app.services.agent_registry import registry

router = APIRouter(prefix="/workflows", tags=["workflows"])

_orchestrator: Optional[WorkflowOrchestrator] = None


def _get_orchestrator() -> WorkflowOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WorkflowOrchestrator(registry=registry)
    return _orchestrator


@router.post(
    "",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create workflow",
    responses={400: {"description": "Validation error / cyclic DAG"}},
)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dag_cfg = payload.dag_config
    if dag_cfg is None and payload.nodes:
        dag_cfg = {"nodes": [n.model_dump(exclude_none=True) for n in payload.nodes]}

    if dag_cfg:
        try:
            parse_dag(dag_cfg)
        except ValueError as exc:
            raise bad_request(str(exc), code="INVALID_WORKFLOW")

    workflow = await workflow_service.create_workflow(db, current_user.id, payload)
    return workflow


@router.get(
    "",
    response_model=PaginatedResponse[WorkflowOut],
    summary="List workflows",
)
async def list_workflows(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    is_active: Optional[bool] = Query(default=None, description="Filter by active state"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total, items = await workflow_service.list_workflows(
        db, current_user.id, skip=skip, limit=limit, is_active=is_active
    )
    has_more = (skip + limit) < total
    response = JSONResponse(
        content=PaginatedResponse[WorkflowOut](
            total=total,
            items=[WorkflowOut.model_validate(w).model_dump(mode="json") for w in items],
            has_more=has_more,
        ).model_dump(mode="json")
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(skip // limit + 1 if limit else 1)
    response.headers["Cache-Control"] = "max-age=300"
    return response


@router.get(
    "/{workflow_id}",
    response_model=WorkflowOut,
    summary="Get workflow DAG + metadata",
    responses={404: {"description": "Workflow not found"}},
)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await workflow_service.get_workflow(db, workflow_id, current_user.id)
    if not workflow:
        raise not_found("Workflow")
    return workflow


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowOut,
    summary="Update workflow DAG / activate / deactivate",
    responses={400: {"description": "Cyclic DAG"}, 404: {"description": "Not found"}},
)
async def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dag_cfg = payload.dag_config
    if dag_cfg is None and payload.nodes:
        dag_cfg = {"nodes": [n.model_dump(exclude_none=True) for n in payload.nodes]}
    if dag_cfg:
        try:
            parse_dag(dag_cfg)
        except ValueError as exc:
            raise bad_request(str(exc), code="INVALID_WORKFLOW")

    workflow = await workflow_service.update_workflow(db, workflow_id, current_user.id, payload)
    if not workflow:
        raise not_found("Workflow")
    return workflow


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete workflow",
    responses={404: {"description": "Workflow not found"}},
)
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await workflow_service.delete_workflow(db, workflow_id, current_user.id)
    if not deleted:
        raise not_found("Workflow")


@router.post(
    "/{workflow_id}/execute",
    response_model=ExecuteWorkflowResponse,
    summary="Execute workflow (async=202, sync=200)",
    responses={
        200: {"description": "Sync execution completed"},
        202: {"description": "Async execution queued"},
        400: {"description": "Inactive workflow"},
        404: {"description": "Workflow not found"},
    },
)
async def execute_workflow(
    workflow_id: UUID,
    payload: ExecuteWorkflowRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await workflow_service.get_workflow(db, workflow_id, current_user.id)
    if not workflow:
        raise not_found("Workflow")
    if not workflow.is_active:
        raise bad_request("Workflow is inactive", code="WORKFLOW_INACTIVE")

    orch = _get_orchestrator()

    try:
        run = await orch.execute_workflow(
            str(workflow_id),
            payload.input_data,
            dag_config=workflow.dag_config or None,
            background=payload.run_async,
        )
    except ValueError as exc:
        raise bad_request(str(exc), code="INVALID_WORKFLOW")

    response_status = status.HTTP_202_ACCEPTED if payload.run_async else status.HTTP_200_OK
    result = None if payload.run_async else run.to_dict()

    return JSONResponse(
        status_code=response_status,
        content=ExecuteWorkflowResponse(
            execution_id=UUID(run.execution_id),
            status="queued" if payload.run_async else run.status,
            result=result,
        ).model_dump(mode="json"),
    )
