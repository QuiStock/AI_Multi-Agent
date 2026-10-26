"""Response contract returned by the FAQ executor."""

from typing import Any, Literal, NotRequired, TypedDict

from src.agents.schemas.tool_call import ToolCalled


class FaqResponse(TypedDict):
    status: Literal["success", "error"]
    answer: str
    tool_called: NotRequired[ToolCalled[dict[str, Any]]]
    error_code: NotRequired[str]
