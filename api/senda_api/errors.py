"""One error shape for the whole API: {"error": {"code", "message"}}. Responses never carry NaN or Infinity."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers  # e.g. Retry-After of a 429
        self.details = details  # more fields of the error body, figures a page can say: {"rows": ..., "limit": ...}


def clean(obj: Any) -> Any:
    """Plain JSON types only: numpy scalars become Python numbers, NaN and infinities become null."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, np.generic):
        return clean(obj.item())
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(clean(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def retry_after(seconds: float) -> dict[str, str]:
    """The header of a refusal that ends by itself: whole seconds, rounded up, at least 1."""
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


def error_response(status: int, code: str, message: str, headers: dict[str, str] | None = None,
                   details: dict[str, Any] | None = None) -> SafeJSONResponse:
    return SafeJSONResponse({"error": {**(details or {}), "code": code, "message": message}}, status_code=status,
                            headers=headers)


def _validation_error(_: Request, exc: RequestValidationError) -> SafeJSONResponse:
    """One code for every malformed request, with the offending fields."""
    fields = [{"loc": [str(p) for p in e["loc"] if p != "body"], "message": str(e["msg"])} for e in exc.errors()]
    first = fields[0] if fields else {"loc": [], "message": "invalid request"}
    where = ".".join(first["loc"])
    message = f"{where}: {first['message']}" if where else first["message"]
    return SafeJSONResponse({"error": {"code": "validation_error", "message": message, "fields": fields}},
                            status_code=422)


def _api_error(_: Request, exc: ApiError) -> SafeJSONResponse:
    return error_response(exc.status, exc.code, exc.message, exc.headers, exc.details)


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def _http_error(_: Request, exc: StarletteHTTPException) -> SafeJSONResponse:
    return error_response(exc.status_code, _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail))


def _unexpected(_: Request, __: Exception) -> SafeJSONResponse:
    return error_response(500, "internal_error", "Internal error")


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
