"""
Agent endpoints — /api/v1/agents
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import not_found
from app.models.database import User
from app.models.db_session import get_db
from app.models.schemas import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    AgentWithStats,
    PaginatedResponse,
    SuccessResponse,
)
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent",
    responses={400: {"description": "Validation error"}},
)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = await agent_service.create_agent(db, current_user.id, payload)
    return agent


@router.get(
    "",
    response_model=PaginatedResponse[AgentOut],
    summary="List agents",
)
async def list_agents(
    skip: int = Query(default=0, ge=0, description="Records to skip"),
    limit: int = Query(default=10, ge=1, le=100, description="Max records to return"),
    role: Optional[str] = Query(default=None, description="Filter by role"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total, items = await agent_service.list_agents(
        db, current_user.id, skip=skip, limit=limit, role=role, status=status_filter
    )
    has_more = (skip + limit) < total
    response = JSONResponse(
        content=PaginatedResponse[AgentOut](
            total=total,
            items=[AgentOut.model_validate(a).model_dump(mode="json") for a in items],
            has_more=has_more,
        ).model_dump(mode="json")
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(skip // limit + 1 if limit else 1)
    response.headers["Cache-Control"] = "max-age=300"
    return response


@router.get(
    "/{agent_id}",
    response_model=AgentWithStats,
    summary="Get agent details + execution stats",
    responses={404: {"description": "Agent not found"}},
)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = await agent_service.get_agent(db, agent_id, current_user.id)
    if not agent:
        raise not_found("Agent")
    stats = await agent_service.get_agent_stats(db, agent_id)
    result = AgentWithStats.model_validate(agent)
    result.stats = stats
    return result


@router.patch(
    "/{agent_id}",
    response_model=AgentOut,
    summary="Partially update agent",
    responses={404: {"description": "Agent not found"}},
)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = await agent_service.update_agent(db, agent_id, current_user.id, payload)
    if not agent:
        raise not_found("Agent")
    return agent


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete agent (marks as archived)",
    responses={404: {"description": "Agent not found"}},
)
async def delete_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await agent_service.delete_agent(db, agent_id, current_user.id)
    if not deleted:
        raise not_found("Agent")
