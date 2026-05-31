import logging as _logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.api import agents, executions, workflows
from app.core.prometheus_metrics import (
    APP_INFO,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
    normalize_path,
)
from app.api.v1 import agents as v1_agents
from app.api.v1 import auth as v1_auth
from app.api.v1 import executions as v1_executions
from app.api.v1 import keys as v1_keys
from app.api.v1 import metrics as v1_metrics
from app.api.v1 import models as v1_models
from app.api.v1 import stream as v1_stream
from app.api.v1 import templates as v1_templates
from app.api.v1 import admin as v1_admin
from app.api.v1 import websocket as v1_websocket
from app.api.v1 import workflows as v1_workflows
from app.core.alert_service import alert_service
from app.core.config import settings
from app.core.errors import HTTP_CODE_MAP
from app.core.logging_config import setup_logging
from app.core.metrics_collector import metrics_collector
from app.core.rate_limiter import BAN_TTL_S, RateLimitResult, RateLimiter
from app.models.database import Base
from app.models.db_session import engine
from app.services.agent_registry import registry

# Configure structured logging with sensitive-data redaction before anything else
_json_logs = settings.ENVIRONMENT == "production"
setup_logging(level="DEBUG" if settings.DEBUG else "INFO", json_logs=_json_logs)

# ── Sentry error tracking ──────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            LoggingIntegration(
                level=_logging.INFO,         # breadcrumbs from INFO+
                event_level=_logging.ERROR,  # send ERROR+ as Sentry events
            ),
        ],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        environment=settings.ENVIRONMENT,
        release=settings.APP_VERSION,
        send_default_pii=False,
    )

import logging
log = logging.getLogger(__name__)

# ── Rate limiter singleton ─────────────────────────────────────────────────────
rate_limiter = RateLimiter(settings.REDIS_URL)

# Paths exempt from rate limiting (health probes, API docs, Prometheus scrape)
_RL_EXEMPT_PATHS: frozenset[str] = frozenset(
    ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]
)
_WORKFLOW_EXEC_RE = re.compile(r"^/api/v1/workflows/[^/]+/execute$")


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, trusting X-Forwarded-For only in production."""
    if settings.ENFORCE_HTTPS:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_user_identifier(request: Request) -> Optional[str]:
    """
    Try to identify the caller from the Authorization header.
    Returns 'user:<id>' for JWT tokens, 'apikey:<prefix>' for API keys, or None.
    Does NOT touch the database — best-effort decode only.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    if token.startswith("sk_live_"):
        return f"apikey:{token[:24]}"
    try:
        from jose import jwt as _jwt
        payload = _jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        uid = payload.get("user_id")
        return f"user:{uid}" if uid else None
    except Exception:
        return None


def _match_endpoint_rule(path: str, method: str) -> Optional[str]:
    """Return the most specific rate-limit rule key for this request path, or None."""
    if path == "/auth/login" and method == "POST":
        return "auth_login"
    if _WORKFLOW_EXEC_RE.match(path):
        return "workflow_execute"
    if path.startswith("/api/v1/agents") or path.startswith("/api/agents"):
        return "api_agents"
    if path.startswith("/api/v1/") or path.startswith("/api/"):
        return "api_v1_default"
    return None


def _make_429(result: RateLimitResult, *, message: str = "") -> JSONResponse:
    msg = message or "Too many requests. Please wait before retrying."
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "RATE_LIMITED", "message": msg}},
        headers={
            "Retry-After": str(max(1, result.retry_after)),
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(result.reset_ts),
        },
    )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-Agent Orchestrator REST API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ─── Middleware stack (applied in reverse order — last added = first executed) ─

# 1. CORS must wrap everything so preflight requests are handled before auth
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Total-Count", "X-Page"],
)


# 2. HTTPS redirect (production only) — before any business logic
@app.middleware("http")
async def enforce_https_middleware(request: Request, call_next):
    if settings.ENFORCE_HTTPS:
        proto = request.headers.get("X-Forwarded-Proto", "")
        if proto == "http":
            https_url = str(request.url).replace("http://", "https://", 1)
            return RedirectResponse(url=https_url, status_code=301)
    return await call_next(request)


# 3. Rate limiting — reject abusive requests before business logic runs
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.RATE_LIMIT_ENABLED or request.url.path in _RL_EXEMPT_PATHS:
        return await call_next(request)

    ip = _get_client_ip(request)

    # ── IP ban check (DDoS protection) ────────────────────────────────────────
    if await rate_limiter.is_banned(ip):
        from app.core.rate_limiter import RateLimitResult as _R
        dummy = _R(allowed=False, limit=1000, remaining=0,
                   reset_ts=int(time.time()) + BAN_TTL_S, retry_after=BAN_TTL_S)
        return _make_429(dummy, message="Your IP has been temporarily blocked due to suspicious activity.")

    # ── Global IP rate limit (DDoS / flood protection) ────────────────────────
    ip_result = await rate_limiter.check(ip, "ip_global")
    if not ip_result.allowed:
        ua = request.headers.get("User-Agent", "")
        if rate_limiter.is_suspicious_ua(ua):
            await rate_limiter.ban_ip(ip)
        return _make_429(ip_result)

    # ── Endpoint-specific rate limit ──────────────────────────────────────────
    rule_key = _match_endpoint_rule(request.url.path, request.method)
    if rule_key is None:
        return await call_next(request)

    from app.core.rate_limiter import RULES
    rule = RULES[rule_key]
    user_id = _extract_user_identifier(request)
    identifier = user_id if (rule.key_by == "user" and user_id) else ip

    result = await rate_limiter.check(identifier, rule_key)
    if not result.allowed:
        return _make_429(result)

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_ts)
    return response


# 4. Security headers — applied to every response
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Tight CSP for API-only server; relax if serving HTML from here
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.ENFORCE_HTTPS:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return response


# 5. Prometheus instrumentation — counter + histogram per request
@app.middleware("http")
async def prometheus_instrumentation_middleware(request: Request, call_next):
    path = normalize_path(request.url.path)
    method = request.method
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
    t0 = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - t0
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
    HTTP_REQUESTS_TOTAL.labels(
        endpoint=path, method=method, status_code=str(response.status_code)
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(endpoint=path, method=method).observe(duration)
    return response


# 6. Request ID + timing + internal metrics recording (innermost)
@app.middleware("http")
async def attach_request_metadata(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info(
        "[%s] %s %s → %d (%.1fms)",
        request_id, request.method, request.url.path, response.status_code, duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    if request.method == "GET" and "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "max-age=300"

    # Record for real-time metrics (skip health/docs to keep data clean)
    if request.url.path not in _RL_EXEMPT_PATHS:
        user_id = _extract_user_identifier(request)
        metrics_collector.record_request(
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
        )

    return response


# ─── Global error handlers ────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        code = HTTP_CODE_MAP.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": detail},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(detail)}},
        )
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
            }
        },
    )


# ─── Startup / shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await registry.start()
    await rate_limiter.startup()
    await metrics_collector.startup()
    alert_service.configure(settings)
    # Publish static app metadata to Prometheus Info metric
    APP_INFO.info({
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "app_name": settings.APP_NAME,
    })
    log.info(
        "App started — environment=%s enforce_https=%s rate_limit=%s redis=%s",
        settings.ENVIRONMENT,
        settings.ENFORCE_HTTPS,
        settings.RATE_LIMIT_ENABLED,
        rate_limiter.using_redis,
    )


@app.on_event("shutdown")
async def on_shutdown():
    await registry.stop()
    await rate_limiter.shutdown()
    await metrics_collector.shutdown()
    await engine.dispose()


# ─── Prometheus metrics scrape endpoint ───────────────────────────────────────
# Unauthenticated — expose only within the cluster (not via the public LB).
# Returns standard Prometheus text format consumed by the prometheus service.

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Legacy API routes (v0 — /api prefix) ─────────────────────────────────────
app.include_router(agents.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")
app.include_router(executions.router, prefix="/api")

# ─── Auth routes (/auth/...) ──────────────────────────────────────────────────
app.include_router(v1_auth.router)
app.include_router(v1_auth.router, prefix="/api/v1")

# ─── v1 API routes — /api/v1 ─────────────────────────────────────────────────
app.include_router(v1_agents.router, prefix="/api/v1")
app.include_router(v1_workflows.router, prefix="/api/v1")
app.include_router(v1_executions.router, prefix="/api/v1")
app.include_router(v1_models.router, prefix="/api/v1")
app.include_router(v1_metrics.router, prefix="/api/v1")
app.include_router(v1_stream.router, prefix="/api/v1")
app.include_router(v1_templates.router, prefix="/api/v1")
app.include_router(v1_keys.router, prefix="/api/v1")
app.include_router(v1_websocket.router)
app.include_router(v1_admin.router, prefix="/api/v1")
