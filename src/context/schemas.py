"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["faq", "clarification_required", "out_of_scope"]


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: Route
    reason: str = Field(min_length=1, max_length=240)
