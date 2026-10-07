"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.context.state import ResponseStatus

Route = Literal["faq", "clarification_required", "out_of_scope"]


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: Route
    reason: str = Field(min_length=1, max_length=240)


class CompilerResult(BaseModel):
    """Structured response produced by the compiler node."""

    content: str = Field(min_length=1, max_length=4000)
    status: ResponseStatus


class AgentValidationResult(BaseModel):
    """Validation summary associated with the compiler execution."""

    status: Literal["passed", "blocked", "needs_revision"]
    reason: str


class OutputGuardrailResult(BaseModel):
    """Reserved structured contract for the future output guardrail."""

    status: Literal["passed", "blocked"]
    reason: str
    violations: list[str] = Field(default_factory=list)
