"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.graphs.state import RouteName


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: RouteName
    reason: str = Field(min_length=1, max_length=240)
    memory_action: Literal[
        "none",
        "pure_recall",
        "faq_context",
        "product_context",
    ] = "none"


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
