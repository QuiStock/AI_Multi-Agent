"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator

from src.agents.schemas.tool_call import ToolCalled

RouterRoute = Literal[
    "faq",
    "product_workflow",
    "clarification_required",
    "out_of_scope",
    "memory_recall",
]


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: RouterRoute
    reason: str = Field(min_length=1, max_length=240)


class RouteResponse(TypedDict):
    """Router executor response passed to the graph adapter."""

    route: RouterRoute
    reason: str
    status: Literal["success", "error"]
    tool_called: NotRequired[ToolCalled[dict[str, Any]]]
    error_code: NotRequired[str]


class GreetingDecision(BaseModel):
    """Structured result of the dedicated greeting classifier."""

    category: Literal["greeting_only", "normal_request"]


class CompilerResult(BaseModel):
    """Structured response produced by the compiler node."""

    content: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    status: Literal[
        "success",
        "clarification_required",
        "out_of_scope",
        "rejected",
        "unavailable",
        "error",
    ]

    @field_validator("citations")
    @classmethod
    def validate_unique_citations(
        cls,
        citations: list[str],
    ) -> list[str]:
        if any(not citation.strip() for citation in citations):
            raise ValueError("Citation IDs cannot be empty")

        if len(citations) != len(set(citations)):
            raise ValueError("Citation IDs cannot be duplicated")

        return citations
