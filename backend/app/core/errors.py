from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    content: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        content["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=content)


def not_found(resource: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": f"{resource} not found"},
    )


def bad_request(message: str, code: str = "BAD_REQUEST", details: Optional[Dict] = None) -> HTTPException:
    detail: Dict[str, Any] = {"code": code, "message": message}
    if details:
        detail["details"] = details
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# HTTP status code → error code mapping used by the global handler
HTTP_CODE_MAP: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}
