from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_session import get_db
from app.models.schemas import ExecutionOut, WorkflowCreate, WorkflowOut
from app.services import workflow_service

router = APIRouter(tags=["workflows"])

_STUB_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _current_user_id() -> UUID:
    return _STUB_USER_ID


@router.post("/workflows", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    return await workflow_service.create_workflow(db, user_id, payload)


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    return await workflow_service.list_workflows(db, user_id)


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    workflow = await workflow_service.get_workflow(db, workflow_id, user_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


@router.post("/workflows/{workflow_id}/execute", response_model=ExecutionOut, status_code=status.HTTP_202_ACCEPTED)
async def execute_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    workflow = await workflow_service.get_workflow(db, workflow_id, user_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow is inactive")
    execution = await workflow_service.trigger_execution(db, workflow_id)
    return execution
