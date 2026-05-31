"""
Metrics endpoint — /api/v1/metrics
Requires auth (stub in Phase 3; real JWT in Phase 4).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_session import get_db
from app.models.schemas import MetricsResponse
from app.services import workflow_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get(
    "",
    response_model=MetricsResponse,
    summary="Execution metrics (auth required)",
)
async def get_metrics(db: AsyncSession = Depends(get_db)):
    data = await workflow_service.get_metrics(db)
    return MetricsResponse(**data)
