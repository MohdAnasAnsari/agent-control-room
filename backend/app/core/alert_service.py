"""
Security alert service.

Responsibilities:
  - Detect suspicious authentication patterns (failed-login threshold, new IPs)
  - Lock accounts that trip the failed-login threshold
  - Dispatch alerts via email and/or Slack webhook
  - Alert on permission-escalation attempts

All dispatch methods swallow exceptions so a misconfigured mailer
never breaks normal request handling.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


# ── Constants (configurable; mirrors values in config.py) ─────────────────────

FAILED_LOGIN_WINDOW_S  = 300   # 5 minutes
FAILED_LOGIN_THRESHOLD = 5     # attempts before account lock


# ── Alert service ─────────────────────────────────────────────────────────────

class AlertService:
    """
    Singleton-friendly security alert service.
    Call alert_service.configure(settings) once at startup.
    """

    def __init__(self) -> None:
        self._smtp_host: str = ""
        self._smtp_port: int = 587
        self._smtp_user: str = ""
        self._smtp_password: str = ""
        self._smtp_from: str = ""
        self._alert_to: str = ""
        self._slack_webhook: str = ""
        self._configured = False

    def configure(self, settings: Any) -> None:
        self._smtp_host     = getattr(settings, "SMTP_HOST", "")
        self._smtp_port     = getattr(settings, "SMTP_PORT", 587)
        self._smtp_user     = getattr(settings, "SMTP_USER", "")
        self._smtp_password = getattr(settings, "SMTP_PASSWORD", "")
        self._smtp_from     = getattr(settings, "SMTP_FROM", "")
        self._alert_to      = getattr(settings, "ALERT_TO_EMAIL", "")
        self._slack_webhook = getattr(settings, "SLACK_WEBHOOK_URL", "")
        self._configured    = True

    # ── Security event hooks ───────────────────────────────────────────────────

    async def on_failed_login(
        self,
        db: "AsyncSession",
        *,
        email: str,
        ip: Optional[str],
        user_id: Optional[UUID],
    ) -> None:
        """
        Called after each failed login attempt.
        If threshold exceeded: lock the user account and dispatch alerts.
        """
        count = await _count_recent_failures(db, email=email, ip=ip)
        if count < FAILED_LOGIN_THRESHOLD:
            return

        user_locked = False
        if user_id:
            user_locked = await _lock_account(db, user_id)

        if user_locked:
            log.warning(
                "SECURITY: Account %s locked after %d failed login attempts from IP %s",
                email, count, ip,
            )
            await self._dispatch(
                subject=f"[SECURITY] Account locked: {email}",
                body=(
                    f"Account {email} has been automatically locked after "
                    f"{count} failed login attempts in {FAILED_LOGIN_WINDOW_S // 60} minutes.\n\n"
                    f"Last attempt from IP: {ip}\n"
                    f"Time: {datetime.now(timezone.utc).isoformat()}"
                ),
            )

    async def on_successful_login(
        self,
        db: "AsyncSession",
        *,
        user_id: Optional[UUID],
        email: str,
        ip: Optional[str],
    ) -> None:
        """Notify user if this is a login from a previously-unseen IP."""
        if not ip or not user_id:
            return
        is_new = await _is_new_ip(db, user_id=user_id, current_ip=ip)
        if not is_new:
            return

        log.info("SECURITY: User %s logged in from new IP %s", email, ip)
        await self._dispatch(
            subject=f"[SECURITY] New IP login detected: {email}",
            body=(
                f"Your account ({email}) was accessed from a new IP address.\n\n"
                f"IP address: {ip}\n"
                f"Time: {datetime.now(timezone.utc).isoformat()}\n\n"
                "If this wasn't you, please change your password immediately and "
                "contact support."
            ),
            to_override=email,   # notify the user, not just ops
        )

    async def on_permission_denied(
        self,
        *,
        user_id: Optional[UUID],
        detail: dict,
    ) -> None:
        """Alert admins when a privilege-escalation attempt is detected."""
        resource = detail.get("resource", "unknown")
        log.warning("SECURITY: Permission denied for user %s on %s", user_id, resource)
        await self._dispatch(
            subject=f"[SECURITY] Permission escalation attempt — user {user_id}",
            body=(
                f"A permission-escalation attempt was detected.\n\n"
                f"User ID : {user_id}\n"
                f"Resource: {resource}\n"
                f"Details : {detail}\n"
                f"Time    : {datetime.now(timezone.utc).isoformat()}"
            ),
        )

    async def on_metric_threshold(
        self,
        *,
        metric: str,
        value: float,
        threshold: float,
        context: str = "",
    ) -> None:
        """Alert when an operational metric breaches its threshold."""
        log.warning("ALERT: %s=%.2f exceeded threshold=%.2f — %s", metric, value, threshold, context)
        await self._dispatch(
            subject=f"[ALERT] {metric} threshold exceeded ({value:.1f} > {threshold})",
            body=(
                f"Operational alert triggered.\n\n"
                f"Metric   : {metric}\n"
                f"Value    : {value:.2f}\n"
                f"Threshold: {threshold:.2f}\n"
                f"Context  : {context}\n"
                f"Time     : {datetime.now(timezone.utc).isoformat()}"
            ),
        )

    # ── Dispatch helpers ───────────────────────────────────────────────────────

    async def _dispatch(
        self,
        subject: str,
        body: str,
        to_override: Optional[str] = None,
    ) -> None:
        """Send alert via email and Slack (each swallows its own errors)."""
        to = to_override or self._alert_to
        if to:
            await asyncio.get_event_loop().run_in_executor(
                None, self._send_email_sync, subject, body, to
            )
        if self._slack_webhook:
            await self._send_slack(subject, body)

    def _send_email_sync(self, subject: str, body: str, to: str) -> None:
        if not self._smtp_host:
            log.debug("Email alert skipped: SMTP_HOST not configured")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = self._smtp_from or self._smtp_user
            msg["To"]      = to
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
                server.ehlo()
                if self._smtp_port in (587, 25):
                    server.starttls()
                if self._smtp_user:
                    server.login(self._smtp_user, self._smtp_password)
                server.sendmail(msg["From"], [to], msg.as_string())
            log.info("Alert email sent to %s: %s", to, subject)
        except Exception as exc:
            log.warning("Alert email failed: %s", exc)

    async def _send_slack(self, subject: str, body: str) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    self._slack_webhook,
                    json={
                        "text": f"*{subject}*\n```{body}```",
                        "mrkdwn": True,
                    },
                )
            log.info("Slack alert sent: %s", subject)
        except Exception as exc:
            log.warning("Slack alert failed: %s", exc)


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def _count_recent_failures(
    db: "AsyncSession",
    *,
    email: str,
    ip: Optional[str],
) -> int:
    """Count failed logins for (email OR ip) in the last FAILED_LOGIN_WINDOW_S seconds."""
    from sqlalchemy import func, or_, select

    from app.models.database import AuditLog

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=FAILED_LOGIN_WINDOW_S)
    conditions = []
    if email:
        conditions.append(
            AuditLog.detail.op("->>")(  "email") == email  # JSON extract
        )
    if ip:
        conditions.append(AuditLog.ip_address == ip)

    if not conditions:
        return 0

    stmt = (
        select(func.count())
        .where(
            AuditLog.action == "user.login_fail",
            AuditLog.timestamp >= cutoff,
            or_(*conditions),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one() or 0


async def _lock_account(db: "AsyncSession", user_id: UUID) -> bool:
    """Set user.is_active = False. Returns True if the account was active and got locked."""
    from app.models.database import User

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    user.is_active = False

    # Write a critical audit entry (bypass alert hooks to avoid recursion)
    from app.core.audit import AuditAction, audit
    await audit(
        db, AuditAction.ACCOUNT_LOCKED,
        user_id=user_id, resource_type="user", resource_id=str(user_id),
        detail={"reason": "failed_login_threshold"},
        _skip_alert=True,
    )
    return True


async def _is_new_ip(
    db: "AsyncSession",
    *,
    user_id: UUID,
    current_ip: str,
    lookback_days: int = 30,
) -> bool:
    """True if current_ip has not appeared in successful logins for this user recently."""
    from sqlalchemy import select

    from app.models.database import AuditLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    stmt = (
        select(AuditLog.ip_address)
        .where(
            AuditLog.action == "user.login",
            AuditLog.user_id == user_id,
            AuditLog.success == True,   # noqa: E712
            AuditLog.timestamp >= cutoff,
        )
        .distinct()
    )
    result = await db.execute(stmt)
    known_ips = {row[0] for row in result.fetchall() if row[0]}
    return current_ip not in known_ips


# ── Singleton ──────────────────────────────────────────────────────────────────

alert_service = AlertService()
