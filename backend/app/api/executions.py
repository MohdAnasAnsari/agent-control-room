from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_session import get_db
from app.models.schemas import ExecutionDetail, ExecutionStepOut
from app.services import workflow_service

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("/{execution_id}", response_model=ExecutionDetail)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    execution = await workflow_service.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    steps = await workflow_service.get_execution_steps(db, execution_id)
    result = ExecutionDetail.model_validate(execution)
    result.steps = [ExecutionStepOut.model_validate(s) for s in steps]
    return result
