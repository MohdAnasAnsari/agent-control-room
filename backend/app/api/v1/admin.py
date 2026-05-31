"""
Admin dashboard endpoints — /api/v1/admin  (admin role required for all routes)

Endpoints:
  GET  /api/v1/admin/audit-logs          paginated audit log with filters
  GET  /api/v1/admin/audit-logs/stats    chart data (login trends, top users, …)
  GET  /api/v1/admin/metrics             real-time p50/p95/p99 + error rate
  GET  /api/v1/admin/metrics/prometheus  Prometheus text-format exposition
  POST /api/v1/admin/retention/cleanup   trigger data retention cleanup
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit
from app.core.deps import require_role
from app.core.metrics_collector import metrics_collector
from app.models.database import AuditLog, Execution, RequestMetric, User
from app.models.db_session import get_db
from app.models.schemas import (
    AuditLogListResponse,
    AuditLogOut,
    AuditLogStats,
    DailyCount,
    EndpointCount,
    MetricsSummaryOut,
    RetentionResult,
    SlowEndpoint,
    UserActivity,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# All admin routes require the "admin" role
_admin = Depends(require_role("admin"))


# ── GET /api/v1/admin/audit-logs ─────────────────────────────────────────────

@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="Query audit logs (admin only)",
    dependencies=[_admin],
)
async def list_audit_logs(
    user_id:    Optional[UUID]     = Query(None, description="Filter by user ID"),
    action:     Optional[str]      = Query(None, description="Filter by action (e.g. user.login)"),
    severity:   Optional[str]      = Query(None, description="Filter by severity (low/medium/high/critical)"),
    success:    Optional[bool]      = Query(None, description="Filter by outcome"),
    resource_type: Optional[str]   = Query(None),
    date_from:  Optional[datetime] = Query(None, description="ISO datetime start"),
    date_to:    Optional[datetime] = Query(None, description="ISO datetime end"),
    skip:       int                = Query(0,   ge=0),
    limit:      int                = Query(50,  ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())

    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
    if success is not None:
        stmt = stmt.where(AuditLog.success == success)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if date_from:
        stmt = stmt.where(AuditLog.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.timestamp <= date_to)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    items = [AuditLogOut.model_validate(r) for r in rows]

    return AuditLogListResponse(total=total, items=items, has_more=(skip + limit) < total)


# ── GET /api/v1/admin/audit-logs/stats ───────────────────────────────────────

@router.get(
    "/audit-logs/stats",
    response_model=AuditLogStats,
    summary="Audit log chart data (admin only)",
    dependencies=[_admin],
)
async def audit_log_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    # ── Login trends: daily successful logins last 30 days ────────────────────
    login_trends = await _daily_action_counts(
        db,
        action=AuditAction.USER_LOGIN,
        since=now - timedelta(days=30),
        success_filter=True,
    )

    # ── Failed auth: daily failed logins last 7 days ──────────────────────────
    failed_trends = await _daily_action_counts(
        db,
        action=AuditAction.USER_LOGIN_FAIL,
        since=now - timedelta(days=7),
        success_filter=False,
    )

    # ── API usage by endpoint (last 24 h) — from audit action prefixes ────────
    api_usage = await _api_usage_by_endpoint(db, since=now - timedelta(hours=24))

    # ── Top users by audit-log activity last 24 h ────────────────────────────
    top_users = await _top_users(db, since=now - timedelta(hours=24))

    return AuditLogStats(
        login_trends=login_trends,
        failed_auth_trends=failed_trends,
        api_usage_by_endpoint=api_usage,
        top_users=top_users,
    )


# ── GET /api/v1/admin/metrics ─────────────────────────────────────────────────

@router.get(
    "/metrics",
    response_model=MetricsSummaryOut,
    summary="Real-time performance metrics (admin only)",
    dependencies=[_admin],
)
async def get_metrics():
    s = metrics_collector.summary(window_s=300)
    return MetricsSummaryOut(
        p50_ms=s.p50_ms,
        p95_ms=s.p95_ms,
        p99_ms=s.p99_ms,
        error_rate=s.error_rate,
        requests_per_minute=s.requests_per_minute,
        sample_count=s.sample_count,
        top_slow_endpoints=[SlowEndpoint(**e) for e in s.top_slow_endpoints],
    )


# ── GET /api/v1/admin/metrics/prometheus ──────────────────────────────────────

@router.get(
    "/metrics/prometheus",
    response_class=PlainTextResponse,
    summary="Prometheus text-format metrics (admin only)",
    dependencies=[_admin],
)
async def prometheus_metrics():
    return metrics_collector.prometheus_text()


# ── POST /api/v1/admin/retention/cleanup ─────────────────────────────────────

@router.post(
    "/retention/cleanup",
    response_model=RetentionResult,
    status_code=status.HTTP_200_OK,
    summary="Delete records older than retention policy (admin only)",
    dependencies=[_admin],
)
async def retention_cleanup(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    from app.core.config import settings

    now = datetime.now(timezone.utc)

    # Audit logs — keep 1 year
    audit_cutoff = now - timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)
    audit_del = await db.execute(
        delete(AuditLog).where(AuditLog.timestamp < audit_cutoff)
    )
    audit_deleted = audit_del.rowcount

    # Request metrics — keep 3 months
    metrics_cutoff = now - timedelta(days=settings.METRICS_RETENTION_DAYS)
    metrics_del = await db.execute(
        delete(RequestMetric).where(RequestMetric.timestamp < metrics_cutoff)
    )
    metrics_deleted = metrics_del.rowcount

    # Execution logs — keep 3 months (soft-delete not applicable; delete directly)
    exec_cutoff = now - timedelta(days=settings.EXECUTION_LOG_RETENTION_DAYS)
    exec_del = await db.execute(
        delete(Execution).where(
            Execution.completed_at.isnot(None),
            Execution.completed_at < exec_cutoff,
        )
    )
    exec_deleted = exec_del.rowcount

    await audit(
        db, AuditAction.RETENTION_CLEANUP,
        user_id=current_user.id,
        resource_type="system",
        detail={
            "audit_logs_deleted": audit_deleted,
            "metrics_deleted":    metrics_deleted,
            "exec_deleted":       exec_deleted,
        },
    )

    return RetentionResult(
        audit_logs_deleted=audit_deleted,
        metrics_deleted=metrics_deleted,
        execution_logs_deleted=exec_deleted,
    )


# ── DB query helpers ──────────────────────────────────────────────────────────

async def _daily_action_counts(
    db: AsyncSession,
    action: str,
    since: datetime,
    success_filter: Optional[bool] = None,
) -> list[DailyCount]:
    stmt = (
        select(
            func.date(AuditLog.timestamp).label("day"),
            func.count().label("cnt"),
        )
        .where(AuditLog.action == action, AuditLog.timestamp >= since)
    )
    if success_filter is not None:
        stmt = stmt.where(AuditLog.success == success_filter)
    stmt = stmt.group_by(func.date(AuditLog.timestamp)).order_by(func.date(AuditLog.timestamp))

    rows = (await db.execute(stmt)).fetchall()
    return [DailyCount(date=str(r.day), count=r.cnt) for r in rows]


async def _api_usage_by_endpoint(
    db: AsyncSession,
    since: datetime,
) -> list[EndpointCount]:
    stmt = (
        select(AuditLog.action, func.count().label("cnt"))
        .where(
            AuditLog.timestamp >= since,
            AuditLog.action.like("%.%"),   # all dotted actions represent API calls
        )
        .group_by(AuditLog.action)
        .order_by(func.count().desc())
        .limit(20)
    )
    rows = (await db.execute(stmt)).fetchall()
    return [EndpointCount(endpoint=r.action, count=r.cnt) for r in rows]


async def _top_users(
    db: AsyncSession,
    since: datetime,
    limit: int = 10,
) -> list[UserActivity]:
    stmt = (
        select(
            AuditLog.user_id,
            func.count().label("cnt"),
        )
        .where(AuditLog.timestamp >= since, AuditLog.user_id.isnot(None))
        .group_by(AuditLog.user_id)
        .order_by(func.count().desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).fetchall()

    # Enrich with emails
    result = []
    for r in rows:
        user = await db.get(User, r.user_id)
        result.append(
            UserActivity(
                user_id=r.user_id,
                email=user.email if user else None,
                request_count=r.cnt,
            )
        )
    return result
