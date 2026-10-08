from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from src.agents.schemas.tool_result import (
    ComposeResponse,
    DirectResponse,
    JsonScalar,
    NoResponse,
    ResponseContent,
    ToolAction,
    ToolError,
    ToolErrorCategory,
    ToolEvidence,
    ToolMetadata,
    ToolResponse,
    ToolResult,
    ToolStatus,
    ToolWarning,
)

DataT = TypeVar("DataT")


@dataclass(frozen=True)
class ToolResultExtras:
    actions: tuple[ToolAction, ...] = ()
    evidence: tuple[ToolEvidence, ...] = ()
    warnings: tuple[ToolWarning, ...] = ()


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


def create_compose_response(
    *,
    intent: str,
    must_include: Sequence[str] = (),
    constraints: Sequence[str] = (),
) -> ComposeResponse:
    return ComposeResponse(
        intent=intent,
        must_include=list(must_include),
        constraints=list(constraints),
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
    response: ComposeResponse,
    data: DataT,
    meta: ToolMetadata,
    extras: ToolResultExtras = ToolResultExtras(),
) -> ToolResult[DataT]:
    return ToolResult[DataT](
        status=ToolStatus.SUCCESS,
        response=response,
        data=data,
        actions=list(extras.actions),
        evidence=list(extras.evidence),
        warnings=list(extras.warnings),
        error=None,
        meta=meta,
    )


def direct_success(
    *,
    content: ResponseContent,
    meta: ToolMetadata,
    data: DataT | None = None,
    extras: ToolResultExtras = ToolResultExtras(),
) -> ToolResult[DataT]:
    return ToolResult[DataT](
        status=ToolStatus.SUCCESS,
        response=DirectResponse(content=content),
        data=data,
        actions=list(extras.actions),
        evidence=list(extras.evidence),
        warnings=list(extras.warnings),
        error=None,
        meta=meta,
    )


def partial_result(
    *,
    response: ToolResponse,
    data: DataT,
    meta: ToolMetadata,
    extras: ToolResultExtras,
    error: ToolError | None = None,
) -> ToolResult[DataT]:
    return ToolResult[DataT](
        status=ToolStatus.PARTIAL,
        response=response,
        data=data,
        actions=list(extras.actions),
        evidence=list(extras.evidence),
        warnings=list(extras.warnings),
        error=error,
        meta=meta,
    )


def tool_error(
    *,
    error: ToolError,
    meta: ToolMetadata,
    content: ResponseContent | None = None,
) -> ToolResult[None]:
    response: DirectResponse | NoResponse = (
        NoResponse() if content is None else DirectResponse(content=content)
    )

    return ToolResult[None](
        status=ToolStatus.ERROR,
        response=response,
        data=None,
        actions=[],
        evidence=[],
        warnings=[],
        error=error,
        meta=meta,
    )
