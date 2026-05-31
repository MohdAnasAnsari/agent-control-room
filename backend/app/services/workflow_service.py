from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Execution, ExecutionStep, Workflow
from app.models.schemas import WorkflowCreate, WorkflowUpdate


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_dag_config(data: WorkflowCreate | WorkflowUpdate) -> Optional[Dict[str, Any]]:
    """Convert nodes/edges v1 request format into the dag_config dict."""
    if data.dag_config is not None:
        return data.dag_config
    nodes = getattr(data, "nodes", None)
    if not nodes:
        return None
    return {
        "nodes": [n.model_dump(exclude_none=True) for n in nodes],
    }


# ─── Workflows ────────────────────────────────────────────────────────────────

async def create_workflow(db: AsyncSession, user_id: UUID, data: WorkflowCreate) -> Workflow:
    dag = _build_dag_config(data) or {}
    workflow = Workflow(user_id=user_id, name=data.name, dag_config=dag)
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


async def list_workflows(
    db: AsyncSession,
    user_id: UUID,
    *,
    skip: int = 0,
    limit: int = 10,
    is_active: Optional[bool] = None,
) -> Tuple[int, List[Workflow]]:
    base = select(Workflow).where(Workflow.user_id == user_id)
    if is_active is not None:
        base = base.where(Workflow.is_active == is_active)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()

    paged = base.offset(skip).limit(limit).order_by(Workflow.created_at.desc())
    items_result = await db.execute(paged)
    items = list(items_result.scalars().all())

    return total, items


async def get_workflow(db: AsyncSession, workflow_id: UUID, user_id: UUID) -> Optional[Workflow]:
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_workflow(
    db: AsyncSession, workflow_id: UUID, user_id: UUID, data: WorkflowUpdate
) -> Optional[Workflow]:
    workflow = await get_workflow(db, workflow_id, user_id)
    if not workflow:
        return None

    if data.name is not None:
        workflow.name = data.name
    if data.is_active is not None:
        workflow.is_active = data.is_active

    new_dag = _build_dag_config(data)
    if new_dag is not None:
        workflow.dag_config = new_dag

    await db.flush()
    await db.refresh(workflow)
    return workflow


async def delete_workflow(db: AsyncSession, workflow_id: UUID, user_id: UUID) -> bool:
    """Soft-delete by setting is_active=False."""
    workflow = await get_workflow(db, workflow_id, user_id)
    if not workflow:
        return False
    workflow.is_active = False
    await db.flush()
    return True


# ─── Executions ───────────────────────────────────────────────────────────────

async def trigger_execution(
    db: AsyncSession,
    workflow_id: UUID,
    input_data: Optional[Dict[str, Any]] = None,
) -> Execution:
    execution = Execution(
        workflow_id=workflow_id,
        status="pending",
        input_data=input_data or {},
        started_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    await db.flush()
    await db.refresh(execution)
    return execution


async def list_executions(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    workflow_id: Optional[UUID] = None,
) -> Tuple[int, List[Execution]]:
    base = select(Execution).where(Execution.status != "deleted")
    if status:
        base = base.where(Execution.status == status)
    if workflow_id:
        base = base.where(Execution.workflow_id == workflow_id)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()

    paged = base.offset(skip).limit(limit).order_by(Execution.started_at.desc())
    items_result = await db.execute(paged)
    items = list(items_result.scalars().all())

    return total, items


async def get_execution(db: AsyncSession, execution_id: UUID) -> Optional[Execution]:
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id, Execution.status != "deleted"
        )
    )
    return result.scalar_one_or_none()


async def get_execution_steps(db: AsyncSession, execution_id: UUID) -> List[ExecutionStep]:
    result = await db.execute(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.timestamp)
    )
    return list(result.scalars().all())


async def delete_execution(db: AsyncSession, execution_id: UUID) -> bool:
    """Soft-delete by setting status=deleted."""
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id, Execution.status != "deleted"
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        return False
    execution.status = "deleted"
    await db.flush()
    return True


async def get_metrics(db: AsyncSession) -> Dict[str, Any]:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_q = await db.execute(
        select(func.count()).where(Execution.status != "deleted")
    )
    total = total_q.scalar_one() or 0

    success_q = await db.execute(
        select(func.count()).where(Execution.status == "completed")
    )
    success = success_q.scalar_one() or 0

    avg_q = await db.execute(
        select(
            func.avg(
                func.extract("epoch", Execution.completed_at)
                - func.extract("epoch", Execution.started_at)
            )
        ).where(
            Execution.status == "completed",
            Execution.completed_at.isnot(None),
            Execution.started_at.isnot(None),
        )
    )
    avg_seconds = avg_q.scalar_one() or 0.0

    from app.models.database import ApiUsage
    tokens_q = await db.execute(
        select(func.sum(ApiUsage.input_tokens + ApiUsage.output_tokens)).where(
            ApiUsage.timestamp >= today_start
        )
    )
    tokens_today = tokens_q.scalar_one() or 0

    return {
        "total_executions": total,
        "success_rate": round(success / total, 4) if total else 0.0,
        "avg_duration_ms": round(float(avg_seconds) * 1000, 1),
        "tokens_used_today": int(tokens_today),
    }
