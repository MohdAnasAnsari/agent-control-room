from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_session import get_db
from app.models.schemas import AgentCreate, AgentOut, AgentUpdate, MessageResponse
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])

# Placeholder: replace with real JWT dependency in Phase 4
_STUB_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _current_user_id() -> UUID:
    return _STUB_USER_ID


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    return await agent_service.create_agent(db, user_id, payload)


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    return await agent_service.list_agents(db, user_id)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    agent = await agent_service.get_agent(db, agent_id, user_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    agent = await agent_service.update_agent(db, agent_id, user_id, payload)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", response_model=MessageResponse)
async def delete_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(_current_user_id),
):
    deleted = await agent_service.delete_agent(db, agent_id, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return MessageResponse(message="Agent deleted")
