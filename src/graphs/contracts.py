"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.graphs.state import RouteName


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: RouteName
    reason: str = Field(min_length=1, max_length=240)


class CompilerResult(BaseModel):
    """Structured response produced by the compiler node."""

    content: str = Field(min_length=1, max_length=4000)
    status: Literal[
        "success",
        "clarification_required",
        "out_of_scope",
        "rejected",
        "unavailable",
        "error",
    ]
