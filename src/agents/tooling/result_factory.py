from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from src.agents.schemas.tool_result import (
    JsonScalar,
    ToolError,
    ToolErrorCategory,
    ToolEvidence,
    ToolMetadata,
    ToolResult,
    ToolStatus,
)

DataT = TypeVar("DataT")


@dataclass(frozen=True)
class ToolResultExtras:
    evidence: tuple[ToolEvidence, ...] = ()


def create_tool_metadata(
    *,
    tool_name: str,
    tool_version: str,
    tool_call_id: str,
    trace_id: str,
    timestamp: datetime | None = None,
) -> ToolMetadata:
    return ToolMetadata(
        tool_name=tool_name,
        tool_version=tool_version,
        tool_call_id=tool_call_id,
        trace_id=trace_id,
        timestamp=timestamp or datetime.now(UTC),
    )


def create_tool_error(
    *,
    code: str,
    category: ToolErrorCategory,
    message: str,
    retryable: bool = False,
    details: dict[str, JsonScalar] | None = None,
) -> ToolError:
    return ToolError(
        code=code,
        category=category,
        message=message,
        retryable=retryable,
        details=details or {},
    )


def compose_success(
    *,
    data: DataT,
    meta: ToolMetadata,
    extras: ToolResultExtras = ToolResultExtras(),
) -> ToolResult[DataT]:
    return ToolResult[DataT](
        status=ToolStatus.SUCCESS,
        data=data,
        evidence=list(extras.evidence),
        error=None,
        meta=meta,
    )


def tool_error(
    *,
    error: ToolError,
    meta: ToolMetadata,
) -> ToolResult[None]:
    return ToolResult[None](
        status=ToolStatus.ERROR,
        data=None,
        evidence=[],
        error=error,
        meta=meta,
    )
