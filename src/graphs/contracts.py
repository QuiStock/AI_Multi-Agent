"""Runtime-validated contracts used at graph boundaries."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from src.graphs.state import RouteName


class RouteDecision(BaseModel):
    """Structured classification returned by the router model."""

    route: RouteName
    reason: str = Field(min_length=1, max_length=240)


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


class JudgeDecision(BaseModel):
    """Structured evidence judgment produced by the judge model."""

    status: Literal[
        "approved",
        "insufficient_evidence",
        "invalid",
    ]
    reason: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )

    @field_validator("evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(
        cls,
        evidence_ids: list[str],
    ) -> list[str]:
        if any(not evidence_id.strip() for evidence_id in evidence_ids):
            raise ValueError("Evidence IDs cannot be empty")

        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs cannot be duplicated")

        return evidence_ids

    @model_validator(mode="after")
    def validate_approved_result(self) -> Self:
        if self.status == "approved" and not self.evidence_ids:
            raise ValueError("An approved judgment must reference evaluated evidence")

        return self
