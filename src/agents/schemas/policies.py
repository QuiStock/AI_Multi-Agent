from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
