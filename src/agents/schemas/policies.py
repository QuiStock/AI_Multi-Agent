from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
