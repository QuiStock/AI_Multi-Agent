"""Shared contract for a tool call captured by an agent executor."""

from typing import Generic, Literal, TypedDict, TypeVar

ToolOutput = TypeVar("ToolOutput")


class ToolCalled(TypedDict, Generic[ToolOutput]):
    """A tool invocation and its agent-visible result."""

    tool_name: str
    status: Literal["success", "error"]
    toolResult: ToolOutput
