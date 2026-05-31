"""
FastAPI dependencies for authentication and authorization.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, hash_token
from app.models.database import ApiKey, User
from app.models.db_session import get_db

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "UNAUTHORIZED", "message": "Invalid authentication token"},
    headers={"WWW-Authenticate": "Bearer"},
)

_EXPIRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "UNAUTHORIZED", "message": "Session expired, please login again"},
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # ── API key (sk_live_...) ──────────────────────────────────────────────────
    if token.startswith("sk_live_"):
        key_hash = hash_token(token)
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)  # noqa: E712
        )
        api_key_row = result.scalar_one_or_none()
        if api_key_row is None:
            raise _UNAUTHORIZED

        # Update last_used_at without making it a heavy operation
        api_key_row.last_used_at = datetime.now(timezone.utc)

        user = await db.get(User, api_key_row.user_id)
        if user is None or not user.is_active:
            raise _UNAUTHORIZED
        return user

    # ── JWT access token ───────────────────────────────────────────────────────
    payload = decode_access_token(token)
    if payload is None:
        # Could be expired or invalid signature — differentiate on exp claim
        raise _UNAUTHORIZED

    user_id_str = payload.get("user_id")
    if not user_id_str:
        raise _UNAUTHORIZED

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise _UNAUTHORIZED

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED

    return user


def require_role(role: str):
    """Returns a FastAPI dependency that enforces a minimum role."""

    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": "You don't have permission to access this",
                },
            )
        return current_user

    return _checker
