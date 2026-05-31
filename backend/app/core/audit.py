"""
Audit logging service — writes to the audit_logs table.

Usage (backward-compatible):
    await audit(db, AuditAction.USER_LOGIN, user_id=user.id, request=request)
    await audit(db, AuditAction.AGENT_CREATE, user_id=user.id, resource_type="agent",
                resource_id=str(agent.id), severity="medium")

Full class-based API:
    logger = AuditLogger(db)
    await logger.log(AuditAction.WORKFLOW_EXECUTE, user_id=..., severity="high")
"""
from __future__ import annotations

import logging
import platform
import sys
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from fastapi import Request

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# ── Syslog handler (Linux/macOS only) ─────────────────────────────────────────

_syslog_handler: Optional[logging.Handler] = None

def _setup_syslog() -> None:
    global _syslog_handler
    if platform.system() in ("Linux", "Darwin") and _syslog_handler is None:
        try:
            from logging.handlers import SysLogHandler
            _syslog_handler = SysLogHandler(address="/dev/log")
            _syslog_handler.setFormatter(
                logging.Formatter("orchestrator-audit: %(levelname)s %(message)s")
            )
            _syslog_handler.setLevel(logging.INFO)
            log.addHandler(_syslog_handler)
        except Exception as exc:
            log.debug("Syslog unavailable: %s", exc)

_setup_syslog()


# ── Action constants ───────────────────────────────────────────────────────────

class AuditAction:
    # Auth
    USER_REGISTER       = "user.register"
    USER_LOGIN          = "user.login"
    USER_LOGIN_FAIL     = "user.login_fail"
    USER_LOGOUT         = "user.logout"
    ACCOUNT_LOCKED      = "account.locked"
    TOKEN_REFRESH       = "token.refresh"

    # API keys
    API_KEY_CREATE      = "api_key.create"
    API_KEY_REVOKE      = "api_key.revoke"

    # Agents
    AGENT_CREATE        = "agent.create"
    AGENT_READ          = "agent.read"
    AGENT_UPDATE        = "agent.update"
    AGENT_DELETE        = "agent.delete"

    # Workflows
    WORKFLOW_CREATE     = "workflow.create"
    WORKFLOW_UPDATE     = "workflow.update"
    WORKFLOW_DELETE     = "workflow.delete"
    WORKFLOW_EXECUTE    = "workflow.execute"
    WORKFLOW_EXECUTE_COMPLETE = "workflow.execute_complete"
    WORKFLOW_EXECUTE_FAIL     = "workflow.execute_fail"

    # Admin / security
    PERMISSION_DENIED   = "permission.denied"
    SETTINGS_CHANGE     = "settings.change"
    DATA_EXPORT         = "data.export"
    RETENTION_CLEANUP   = "retention.cleanup"
    NEW_IP_LOGIN        = "security.new_ip_login"


# ── Default severity per action ────────────────────────────────────────────────

_ACTION_SEVERITY: dict[str, str] = {
    AuditAction.USER_REGISTER:            "medium",
    AuditAction.USER_LOGIN:               "high",
    AuditAction.USER_LOGIN_FAIL:          "high",
    AuditAction.USER_LOGOUT:              "high",
    AuditAction.ACCOUNT_LOCKED:           "critical",
    AuditAction.TOKEN_REFRESH:            "low",
    AuditAction.API_KEY_CREATE:           "high",
    AuditAction.API_KEY_REVOKE:           "high",
    AuditAction.AGENT_CREATE:             "medium",
    AuditAction.AGENT_READ:               "low",
    AuditAction.AGENT_UPDATE:             "medium",
    AuditAction.AGENT_DELETE:             "medium",
    AuditAction.WORKFLOW_CREATE:          "medium",
    AuditAction.WORKFLOW_UPDATE:          "medium",
    AuditAction.WORKFLOW_DELETE:          "medium",
    AuditAction.WORKFLOW_EXECUTE:         "high",
    AuditAction.WORKFLOW_EXECUTE_COMPLETE:"high",
    AuditAction.WORKFLOW_EXECUTE_FAIL:    "high",
    AuditAction.PERMISSION_DENIED:        "high",
    AuditAction.SETTINGS_CHANGE:          "low",
    AuditAction.DATA_EXPORT:              "high",
    AuditAction.RETENTION_CLEANUP:        "medium",
    AuditAction.NEW_IP_LOGIN:             "high",
}

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def severity_for_action(action: str) -> str:
    """Return the default severity string for a given action."""
    return _ACTION_SEVERITY.get(action, "low")


# ── Core write function (backward-compatible) ─────────────────────────────────

async def audit(
    db: "AsyncSession",
    action: str,
    *,
    user_id: Optional[UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    request: Optional[Request] = None,
    success: bool = True,
    detail: Optional[dict[str, Any]] = None,
    severity: Optional[str] = None,
    _skip_alert: bool = False,
) -> None:
    """
    Write one audit log entry.  Shares the caller's DB session so it commits
    atomically with the surrounding transaction.

    If `severity` is None it is inferred from the action name.
    Set `_skip_alert=True` internally to avoid re-entrant alert checks.
    """
    from app.models.database import AuditLog

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    if request is not None:
        client = request.client
        ip_address = client.host if client else None
        user_agent = request.headers.get("user-agent")

    effective_severity = severity or severity_for_action(action)

    record = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        detail=detail,
        severity=effective_severity,
    )
    db.add(record)

    _emit_structured_log(action, user_id, resource_type, resource_id, success, effective_severity)

    # Security-alert side-effects (non-blocking; failures are swallowed)
    if not _skip_alert:
        await _run_alert_hooks(
            db=db,
            action=action,
            user_id=user_id,
            ip_address=ip_address,
            success=success,
            detail=detail or {},
        )


def _emit_structured_log(
    action: str,
    user_id: Optional[UUID],
    resource_type: Optional[str],
    resource_id: Optional[str],
    success: bool,
    severity: str,
) -> None:
    """Emit a structured log line at the appropriate level."""
    level = {
        "low":      logging.DEBUG,
        "medium":   logging.INFO,
        "high":     logging.WARNING,
        "critical": logging.CRITICAL,
    }.get(severity, logging.INFO)

    log.log(
        level,
        "AUDIT action=%s user_id=%s resource=%s/%s success=%s severity=%s",
        action, user_id, resource_type, resource_id, success, severity,
    )


async def _run_alert_hooks(
    db: "AsyncSession",
    action: str,
    user_id: Optional[UUID],
    ip_address: Optional[str],
    success: bool,
    detail: dict,
) -> None:
    """Fire security-alert checks after writing the audit entry."""
    try:
        from app.core.alert_service import alert_service

        if action == AuditAction.USER_LOGIN_FAIL:
            email = detail.get("email", "")
            await alert_service.on_failed_login(db, email=email, ip=ip_address, user_id=user_id)

        elif action == AuditAction.USER_LOGIN and success:
            email = detail.get("email", "")
            await alert_service.on_successful_login(db, user_id=user_id, email=email, ip=ip_address)

        elif action == AuditAction.PERMISSION_DENIED:
            await alert_service.on_permission_denied(user_id=user_id, detail=detail)

    except Exception as exc:
        log.warning("Alert hook failed (non-fatal): %s", exc)


# ── Class-based API (preferred for new code) ──────────────────────────────────

class AuditLogger:
    """
    Stateful audit logger tied to a DB session.

    Usage:
        logger = AuditLogger(db)
        await logger.log(AuditAction.AGENT_CREATE, user_id=user.id,
                         resource_type="agent", resource_id=str(agent.id))
    """

    def __init__(self, db: "AsyncSession") -> None:
        self._db = db

    async def log(
        self,
        action: str,
        *,
        user_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        request: Optional[Request] = None,
        success: bool = True,
        detail: Optional[dict[str, Any]] = None,
        severity: Optional[str] = None,
    ) -> None:
        await audit(
            self._db,
            action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            request=request,
            success=success,
            detail=detail,
            severity=severity,
        )

    async def log_high(self, action: str, **kwargs: Any) -> None:
        """Shortcut to force high severity."""
        kwargs.setdefault("severity", "high")
        await self.log(action, **kwargs)

    async def log_critical(self, action: str, **kwargs: Any) -> None:
        """Shortcut to force critical severity."""
        kwargs.setdefault("severity", "critical")
        await self.log(action, **kwargs)
