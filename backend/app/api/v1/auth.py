"""
Authentication endpoints — /auth

Login rate limiting (5 req/min per IP) is enforced by the global rate-limit
middleware in app.main. No per-endpoint logic needed here.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models.database import RefreshToken, User
from app.models.db_session import get_db
from app.models.schemas import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _make_access_payload(user: User) -> dict:
    return {"user_id": str(user.id), "email": user.email, "role": user.role}


async def _store_refresh_token(db: AsyncSession, user_id, raw_token: str) -> None:
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    record = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(record)


# ── POST /auth/register ────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserOut,
    summary="Register new user",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    errors = validate_password_strength(payload.password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "WEAK_PASSWORD", "message": errors[0], "details": {"errors": errors}},
        )

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": "Email already registered"},
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role="user",
    )
    db.add(user)
    await db.flush()

    await audit(db, AuditAction.USER_REGISTER,
                user_id=user.id, resource_type="user",
                resource_id=str(user.id), request=request)
    return user


# ── POST /auth/login ───────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive JWT tokens",
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user: Optional[User] = result.scalar_one_or_none()

    # Generic error — never reveal whether the email exists
    if not user or not verify_password(payload.password, user.hashed_password):
        # Audit failed login (user_id may be None if email unknown)
        await audit(db, AuditAction.USER_LOGIN_FAIL,
                    user_id=user.id if user else None,
                    resource_type="user", request=request, success=False,
                    detail={"email": payload.email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid email or password"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Account is disabled"},
        )

    access_token = create_access_token(_make_access_payload(user))
    raw_refresh, _ = create_refresh_token()
    await _store_refresh_token(db, user.id, raw_refresh)

    await audit(db, AuditAction.USER_LOGIN,
                user_id=user.id, resource_type="user",
                resource_id=str(user.id), request=request,
                detail={"email": user.email})

    # httpOnly cookie — JS cannot access it
    response.set_cookie(
        key="refresh_token",
        value=raw_refresh,
        httponly=True,
        secure=settings.ENFORCE_HTTPS,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        # Allow refresh from both `/auth/refresh` (legacy) and `/api/v1/auth/refresh` (v1)
        path="/",
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        user=UserOut.model_validate(user),
    )


# ── POST /auth/refresh ─────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Get new access token from refresh token",
)
async def refresh_token(
    request: Request,
    payload: Optional[RefreshRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    raw_token: Optional[str] = request.cookies.get("refresh_token")
    if not raw_token and payload:
        raw_token = payload.refresh_token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": "refresh_token is required"},
        )

    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record: Optional[RefreshToken] = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if (
        record is None
        or record.is_blacklisted
        or record.expires_at.replace(tzinfo=timezone.utc) < now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Session expired, please login again"},
        )

    user = await db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid authentication token"},
        )

    await audit(db, AuditAction.TOKEN_REFRESH,
                user_id=user.id, resource_type="token", request=request)

    access_token = create_access_token(_make_access_payload(user))
    return AccessTokenResponse(access_token=access_token)


# ── POST /auth/logout ──────────────────────────────────────────────────────────

@router.post(
    "/logout",
    summary="Logout and invalidate refresh token",
)
async def logout(
    request: Request,
    response: Response,
    payload: Optional[LogoutRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    raw_token: Optional[str] = request.cookies.get("refresh_token")
    if not raw_token and payload:
        raw_token = payload.refresh_token

    user_id = None
    if raw_token:
        token_hash = hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record: Optional[RefreshToken] = result.scalar_one_or_none()
        if record and not record.is_blacklisted:
            record.is_blacklisted = True
            user_id = record.user_id

    await audit(db, AuditAction.USER_LOGOUT,
                user_id=user_id, resource_type="user", request=request)

    response.delete_cookie(key="refresh_token", path="/")
    return {"success": True}
