"""
Structured logging configuration with sensitive-data redaction.

In development (ENVIRONMENT != "production"):
    Text format: "2024-01-15T14:30:45 INFO [app.main] Message"

In production (ENVIRONMENT == "production"):
    JSON format compatible with ELK / CloudWatch / Datadog:
    {"timestamp":"...","level":"INFO","logger":"app.main","message":"...","service":"orchestrator-backend"}

Call setup_logging() once at application startup.
"""

import json
import logging
import logging.config
import re
import time
from typing import Optional


# ── Redaction patterns ─────────────────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'sk_live_[A-Za-z0-9]{32}'), 'sk_live_***'),
    (re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]{8,}'), r'\1[REDACTED]'),
    (re.compile(r'("password"\s*:\s*)"[^"]*"'), r'\1"***"'),
    (re.compile(r'(password=)[^&\s"\']+'), r'\1***'),
    (re.compile(r'("hashed_password"\s*:\s*)"[^"]*"'), r'\1"***"'),
    (re.compile(r'("refresh_token"\s*:\s*)"([^"]{8})[^"]*"'), r'\1"\2...[REDACTED]"'),
    (re.compile(r'\b([A-Za-z0-9_\-]{4,})\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\b'),
     lambda m: m.group()[:8] + '...[JWT]'),
    (re.compile(r'(sk-ant-|sk-)[A-Za-z0-9\-]{20,}'), r'\1***'),
    (re.compile(r'("(?:api_key|secret|token)"\s*:\s*)"[A-Za-z0-9_\-\.]{16,}"'), r'\1"***"'),
]


class SensitiveFilter(logging.Filter):
    """Strips secrets from every log record before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True

        for pattern, replacement in _PATTERNS:
            if callable(replacement):
                msg = pattern.sub(replacement, msg)
            else:
                msg = pattern.sub(replacement, msg)

        record.msg = msg
        record.args = ()
        return True


# ── JSON formatter ─────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """
    Emits one JSON object per log line.
    Compatible with ELK, AWS CloudWatch, Datadog, and GCP Logging.

    Fields emitted:
        timestamp  — ISO-8601 UTC
        level      — DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger     — dotted logger name (e.g. "app.core.rate_limiter")
        service    — always "orchestrator-backend"
        message    — the formatted log message
        exc_info   — exception traceback (only when present)
        request_id — if set on the record (added by request-id middleware)
        user_id    — if set on the record
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, datefmt=None),
            "level": record.levelname,
            "logger": record.name,
            "service": "orchestrator-backend",
            "message": record.getMessage(),
        }

        # Optional context fields attached by middleware
        for field in ("request_id", "user_id", "workflow_id", "execution_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str]) -> str:  # type: ignore[override]
        return (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z"
        )


# ── Setup ──────────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """
    Configure root logger with the SensitiveFilter applied to every handler.
    Pass json_logs=True (or set ENVIRONMENT=production) to emit JSON.
    Call once from main.py before the app starts handling requests.
    """
    sensitive_filter = SensitiveFilter()

    root = logging.getLogger()
    root.setLevel(level)

    # Remove pre-existing handlers (Uvicorn/FastAPI may have added some)
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()

    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))

    handler.addFilter(sensitive_filter)
    root.addHandler(handler)

    # Attach filter to uvicorn loggers so access logs are also redacted
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lgr = logging.getLogger(logger_name)
        lgr.addFilter(sensitive_filter)

    logging.getLogger(__name__).info(
        "Logging configured: level=%s json=%s", level, json_logs
    )
