"""
Models endpoint — /api/v1/models
Returns available LLM models grouped by tier.
"""

from fastapi import APIRouter

from app.models.schemas import ModelsResponse

router = APIRouter(prefix="/models", tags=["models"])

_TESTING = ["mixtral-8x7b", "llama-2-70b", "llama-3.3-70b-versatile"]
_PRODUCTION = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "gpt-4o", "gpt-4o-mini"]


@router.get(
    "",
    response_model=ModelsResponse,
    summary="List available LLM models by tier",
)
async def list_models():
    return ModelsResponse(testing=_TESTING, production=_PRODUCTION)
