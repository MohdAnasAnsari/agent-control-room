"""
Prometheus metric definitions for the Multi-Agent Orchestrator.

Declare all metrics here so they are registered exactly once.
Import specific metrics in middleware, services, and LLM providers to record data.

Label cardinality note: endpoint labels have UUIDs stripped to {id} by
normalize_path() so Prometheus doesn't create an unbounded series.
"""
from __future__ import annotations

import re

from prometheus_client import Counter, Gauge, Histogram, Info

# ── Path normalizer ────────────────────────────────────────────────────────────
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def normalize_path(path: str) -> str:
    """Replace UUID path segments with {id} to prevent high cardinality."""
    return _UUID_RE.sub("{id}", path)


# ── HTTP request metrics ───────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests by endpoint, method, and status code",
    ["endpoint", "method", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint", "method"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method"],
)

# ── Workflow execution metrics ─────────────────────────────────────────────────

WORKFLOW_EXECUTIONS_TOTAL = Counter(
    "workflow_executions_total",
    "Workflow executions by final status",
    ["status"],  # success | failure | timeout
)

WORKFLOW_EXECUTION_DURATION_SECONDS = Histogram(
    "workflow_execution_duration_seconds",
    "Workflow execution wall-clock time in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800],
)

WORKFLOW_ACTIVE = Gauge(
    "workflow_executions_active",
    "Workflow executions currently in progress",
)

# ── LLM provider metrics ───────────────────────────────────────────────────────

LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "LLM API calls by provider, model, and outcome",
    ["provider", "model", "status"],  # status: success | error | timeout
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "llm_request_duration_seconds",
    "LLM API round-trip latency in seconds",
    ["provider", "model"],
    buckets=[0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "LLM tokens consumed, labelled by provider, model, and direction",
    ["provider", "model", "direction"],  # direction: input | output
)

LLM_COST_USD_TOTAL = Counter(
    "llm_cost_usd_total",
    "Estimated LLM spend in USD (best-effort, uses public pricing)",
    ["provider", "model"],
)

# ── Database metrics ────────────────────────────────────────────────────────────

DB_POOL_SIZE = Gauge(
    "db_pool_size",
    "Configured size of the SQLAlchemy connection pool",
)

DB_POOL_CHECKED_OUT = Gauge(
    "db_pool_checked_out",
    "Database connections currently checked out from the pool",
)

DB_POOL_OVERFLOW = Gauge(
    "db_pool_overflow",
    "Database connections above pool_size in use (overflow connections)",
)

# ── Authentication metrics ─────────────────────────────────────────────────────

AUTH_LOGIN_TOTAL = Counter(
    "auth_login_total",
    "Login attempts by outcome",
    ["outcome"],  # success | failure | locked
)

AUTH_TOKEN_ISSUED_TOTAL = Counter(
    "auth_tokens_issued_total",
    "JWT tokens issued by type",
    ["token_type"],  # access | refresh
)

# ── Application info ────────────────────────────────────────────────────────────

APP_INFO = Info(
    "app_build",
    "Static application metadata (version, environment)",
)
