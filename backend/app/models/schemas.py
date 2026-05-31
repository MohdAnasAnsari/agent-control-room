from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

T = TypeVar("T")

# ─── Shared ───────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = {"from_attributes": True}


# ─── Pagination ───────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    items: List[T]
    has_more: bool


# ─── Error ────────────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ─── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(OrmBase):
    id: UUID
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


# ─── API Keys ─────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyOut(OrmBase):
    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class ApiKeyCreated(ApiKeyOut):
    key: str  # raw key — only returned once, never again


# ─── User (kept for backward compat) ──────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


# ─── Agent ────────────────────────────────────────────────────────────────────

ALLOWED_MODELS = {
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "gpt-4o",
    "gpt-4o-mini",
    "llama-3.3-70b-versatile",
}


class AgentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=50)
    role: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(min_length=20, max_length=2000)
    model: str = Field(default="claude-sonnet-4-6", max_length=100)
    tools: List[str] = Field(default_factory=list)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(f"Model must be one of: {', '.join(sorted(ALLOWED_MODELS))}")
        return v


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=50)
    role: Optional[str] = Field(default=None, min_length=1, max_length=100)
    system_prompt: Optional[str] = Field(default=None, min_length=20, max_length=2000)
    model: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = None
    tools: Optional[List[str]] = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_MODELS:
            raise ValueError(f"Model must be one of: {', '.join(sorted(ALLOWED_MODELS))}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"active", "paused", "archived"}:
            raise ValueError("status must be active, paused, or archived")
        return v


class AgentStats(OrmBase):
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0


class AgentOut(OrmBase):
    id: UUID
    user_id: UUID
    name: str
    role: str
    system_prompt: str
    model: str
    status: str
    tools: List[str] = Field(default_factory=list)
    created_at: datetime


class AgentWithStats(AgentOut):
    stats: AgentStats = Field(default_factory=AgentStats)


# ─── Workflow ─────────────────────────────────────────────────────────────────

class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: str = Field(default="agent")
    agent_id: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    condition: Optional[str] = None
    true_branch: Optional[str] = None
    false_branch: Optional[str] = None
    timeout_s: float = 60.0


class WorkflowEdge(BaseModel):
    source: str
    target: str


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    dag_config: Optional[Dict[str, Any]] = None  # backward compat — takes precedence if set


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    nodes: Optional[List[WorkflowNode]] = None
    edges: Optional[List[WorkflowEdge]] = None
    is_active: Optional[bool] = None
    dag_config: Optional[Dict[str, Any]] = None


class WorkflowOut(OrmBase):
    id: UUID
    user_id: UUID
    name: str
    dag_config: Dict[str, Any]
    is_active: bool
    created_at: datetime


# ─── Execution ────────────────────────────────────────────────────────────────

class ExecuteWorkflowRequest(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)
    run_async: bool = True


class ExecuteWorkflowResponse(BaseModel):
    execution_id: UUID
    status: str
    result: Optional[Dict[str, Any]] = None


class ExecutionOut(OrmBase):
    id: UUID
    workflow_id: UUID
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_log: Optional[str] = None


class ExecutionStepOut(OrmBase):
    id: UUID
    execution_id: UUID
    agent_id: Optional[UUID] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None
    timestamp: datetime


class ExecutionDetail(ExecutionOut):
    steps: List[ExecutionStepOut] = Field(default_factory=list)


# ─── Metrics ──────────────────────────────────────────────────────────────────

class MetricsResponse(BaseModel):
    total_executions: int
    success_rate: float
    avg_duration_ms: float
    tokens_used_today: int


# ─── Models ───────────────────────────────────────────────────────────────────

class ModelsResponse(BaseModel):
    testing: List[str]
    production: List[str]


# ─── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime


# ─── Generic ──────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class SuccessResponse(BaseModel):
    success: bool = True


# ─── Audit logs ───────────────────────────────────────────────────────────────

class AuditLogOut(OrmBase):
    id: UUID
    timestamp: datetime
    user_id: Optional[UUID] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool
    detail: Optional[Dict[str, Any]] = None
    severity: str = "low"


# ─── Admin dashboard / audit stats ───────────────────────────────────────────

class DailyCount(BaseModel):
    date: str           # ISO date e.g. "2026-05-30"
    count: int


class EndpointCount(BaseModel):
    endpoint: str
    count: int


class UserActivity(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    request_count: int


class AuditLogStats(BaseModel):
    login_trends: List[DailyCount]          # last 30 days
    failed_auth_trends: List[DailyCount]    # last 7 days
    api_usage_by_endpoint: List[EndpointCount]  # last 24 h (from audit logs)
    top_users: List[UserActivity]           # last 24 h


class AuditLogListResponse(BaseModel):
    total: int
    items: List[AuditLogOut]
    has_more: bool


# ─── Metrics / performance ────────────────────────────────────────────────────

class SlowEndpoint(BaseModel):
    endpoint: str
    avg_ms: float
    count: int


class MetricsSummaryOut(BaseModel):
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    requests_per_minute: float
    sample_count: int
    top_slow_endpoints: List[SlowEndpoint]


# ─── Retention ────────────────────────────────────────────────────────────────

class RetentionResult(BaseModel):
    audit_logs_deleted: int
    metrics_deleted: int
    execution_logs_deleted: int
