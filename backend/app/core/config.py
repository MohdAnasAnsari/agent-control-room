from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Multi-Agent Orchestrator"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"   # development | production

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/orchestrator"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_SSL_MODE: str = ""        # "require" in production; empty = disabled

    # Security
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24   # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Encryption at rest (Fernet, derived via PBKDF2 from this key)
    # Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
    ENCRYPTION_KEY: str = secrets.token_urlsafe(32)

    # HTTPS enforcement
    # Set True in production — redirects HTTP → HTTPS and forces Secure cookies
    ENFORCE_HTTPS: bool = False

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
    ]

    # AI Provider API Keys
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # LLM defaults
    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    TEST_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TIMEOUT_S: float = 30.0
    LLM_MAX_RETRIES: int = 3
    LLM_FALLBACK_ENABLED: bool = True

    # Redis (used for distributed rate limiting; falls back to in-memory if unavailable)
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Observability ──────────────────────────────────────────────────────────
    # Sentry — leave empty to disable error tracking
    SENTRY_DSN: str = ""
    # Fraction of transactions to send to Sentry for performance monitoring (0–1)
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True

    # Execution resource limits
    MAX_EXECUTION_TIME_S: int = 1800       # 30 minutes
    MAX_PARALLEL_NODES: int = 20
    MAX_TOKENS_PER_EXECUTION: int = 1_000_000
    MAX_UPLOAD_SIZE_MB: int = 100

    # ── Alerting / notifications ───────────────────────────────────────────────
    # Email (SMTP) — leave SMTP_HOST empty to disable
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    ALERT_TO_EMAIL: str = ""            # ops / security team inbox

    # Slack — leave empty to disable
    SLACK_WEBHOOK_URL: str = ""

    # ── Security alert thresholds ──────────────────────────────────────────────
    FAILED_LOGIN_LOCK_THRESHOLD: int = 5     # attempts before account lock
    FAILED_LOGIN_WINDOW_S: int = 300         # within this many seconds

    # ── Metrics alerting thresholds ────────────────────────────────────────────
    ALERT_ERROR_RATE: float = 0.05           # 5%
    ALERT_P95_LATENCY_MS: float = 5000.0
    ALERT_EXEC_FAIL_RATE: float = 0.20       # 20%

    # ── Data retention ─────────────────────────────────────────────────────────
    AUDIT_LOG_RETENTION_DAYS: int = 365      # 1 year
    METRICS_RETENTION_DAYS: int = 90         # 3 months
    EXECUTION_LOG_RETENTION_DAYS: int = 90   # 3 months

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
