"""
API key management — /api/v1/keys
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit
from app.core.deps import get_current_user
from app.core.security import generate_api_key, hash_token
from app.models.database import ApiKey, User
from app.models.db_session import get_db
from app.models.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/keys", tags=["api-keys"])

_KEY_PREFIX_LEN = 16  # "sk_live_XXXXXXXX" — first 16 chars shown in listing


@router.get(
    "",
    response_model=list[ApiKeyOut],
    summary="List API keys for current user",
)
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id, ApiKey.is_active == True)  # noqa: E712
        .order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key",
)
async def create_key(
    payload: ApiKeyCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw_key = generate_api_key()
    key_hash = hash_token(raw_key)
    key_prefix = raw_key[:_KEY_PREFIX_LEN]

    api_key = ApiKey(
        user_id=current_user.id,
        key_prefix=key_prefix,
        key_hash=key_hash,
        name=payload.name,
    )
    db.add(api_key)
    await db.flush()

    await audit(db, AuditAction.API_KEY_CREATE,
                user_id=current_user.id, resource_type="api_key",
                resource_id=str(api_key.id), request=request,
                detail={"name": payload.name})

    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        key=raw_key,
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "API key not found"},
        )

    api_key.is_active = False

    await audit(db, AuditAction.API_KEY_REVOKE,
                user_id=current_user.id, resource_type="api_key",
                resource_id=str(key_id), request=request)
