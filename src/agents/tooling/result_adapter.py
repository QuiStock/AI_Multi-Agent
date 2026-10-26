from __future__ import annotations

import json
from typing import Any, TypeVar

from src.agents.schemas.tool_result import ToolResult

DataT = TypeVar("DataT")


def build_agent_view(
    result: ToolResult[DataT],
) -> dict[str, Any]:
    return result.model_dump(
        mode="json",
        exclude_none=False,
    )


def serialize_for_agent(
    result: ToolResult[DataT],
) -> str:
    return json.dumps(
        build_agent_view(result),
        ensure_ascii=False,
        separators=(",", ":"),
    )
