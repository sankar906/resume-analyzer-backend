"""Shared API response envelopes."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """Standard API response wrapper."""

    success: bool = True
    message: str = "Operation successful"
    data: Optional[Union[dict[str, Any], list[Any], Any]] = Field(
        default=None,
        description="Payload: object, array, or null.",
    )


class ErrorResponse(BaseModel):
    """Error response model (use with HTTPException or exception handlers)."""

    success: bool = False
    message: str
    error_code: Optional[str] = None
    details: Optional[dict[str, Any]] = None
