from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Agent, ExecutionStep
from app.models.schemas import AgentCreate, AgentStats, AgentUpdate


async def create_agent(db: AsyncSession, user_id: UUID, data: AgentCreate) -> Agent:
    agent = Agent(user_id=user_id, **data.model_dump())
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def list_agents(
    db: AsyncSession,
    user_id: UUID,
    *,
    skip: int = 0,
    limit: int = 10,
    role: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[int, List[Agent]]:
    base = select(Agent).where(Agent.user_id == user_id)
    if role:
        base = base.where(Agent.role == role)
    if status:
        base = base.where(Agent.status == status)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()

    paged = base.offset(skip).limit(limit).order_by(Agent.created_at.desc())
    items_result = await db.execute(paged)
    items = list(items_result.scalars().all())

    return total, items


async def get_agent(db: AsyncSession, agent_id: UUID, user_id: UUID) -> Optional[Agent]:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_agent(
    db: AsyncSession, agent_id: UUID, user_id: UUID, data: AgentUpdate
) -> Optional[Agent]:
    agent = await get_agent(db, agent_id, user_id)
    if not agent:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.flush()
    await db.refresh(agent)
    return agent


async def delete_agent(db: AsyncSession, agent_id: UUID, user_id: UUID) -> bool:
    """Soft-delete by marking status=archived."""
    agent = await get_agent(db, agent_id, user_id)
    if not agent:
        return False
    agent.status = "archived"
    await db.flush()
    return True


async def get_agent_stats(db: AsyncSession, agent_id: UUID) -> AgentStats:
    total_q = await db.execute(
        select(func.count()).where(ExecutionStep.agent_id == agent_id)
    )
    total = total_q.scalar_one() or 0

    successful_q = await db.execute(
        select(func.count()).where(
            ExecutionStep.agent_id == agent_id,
            ExecutionStep.output.isnot(None),
        )
    )
    successful = successful_q.scalar_one() or 0

    return AgentStats(
        total_executions=total,
        successful_executions=successful,
        failed_executions=max(0, total - successful),
    )
