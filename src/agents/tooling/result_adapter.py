from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar

from src.agents.schemas.tool_result import (
    ToolAction,
    ToolEvidence,
    ToolMetadata,
    ToolResult,
)

DataT = TypeVar("DataT")


@dataclass(frozen=True)
class ToolResultProjection:
    agent_content: str
    state_record: dict[str, Any]
    actions: tuple[ToolAction, ...]
    evidence: tuple[ToolEvidence, ...]
    metadata: ToolMetadata


def deserialize_tool_result(
    payload: str | bytes | bytearray,
    *,
    result_model: type[ToolResult[DataT]],
) -> ToolResult[DataT]:
    return result_model.model_validate_json(payload)


def build_agent_view(
    result: ToolResult[DataT],
) -> dict[str, Any]:
    agent_view = result.model_dump(
        mode="json",
        exclude_none=False,
    )

    agent_view.pop("meta", None)

    error = agent_view.get("error")

    if isinstance(error, dict):
        error.pop("details", None)

    return agent_view


def serialize_for_agent(
    result: ToolResult[DataT],
) -> str:
    return json.dumps(
        build_agent_view(result),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def serialize_for_state(
    result: ToolResult[DataT],
) -> dict[str, Any]:
    return result.model_dump(
        mode="json",
        exclude_none=False,
    )


def project_tool_result(
    result: ToolResult[DataT],
) -> ToolResultProjection:
    return ToolResultProjection(
        agent_content=serialize_for_agent(result),
        state_record=serialize_for_state(result),
        actions=tuple(result.actions),
        evidence=tuple(result.evidence),
        metadata=result.meta,
    )
