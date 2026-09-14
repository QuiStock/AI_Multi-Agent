from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    mode: Literal[
        "none",
        "recent",
        "long_term",
        "both",
    ] = "none"

    max_items: int = Field(default=0, ge=0)
    ttl_hours: int | None = Field(default=None, gt=0)


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_evidence: bool = False
    requires_citations: bool = False
    minimum_sources: int = Field(default=0, ge=0)


class FailurePolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    on_timeout: Literal[
        "retry",
        "fallback",
        "fail",
    ] = "fail"

    max_retries: int = Field(default=0, ge=0)
    fallback_message: str | None = None


class PromptVariable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True

    source: Literal[
        "message",
        "state",
        "identity",
        "runtime",
    ]
