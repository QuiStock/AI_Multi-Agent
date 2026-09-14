from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ToolValueType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "array",
    "object",
]


class ToolProperty(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    name: str = Field(min_length=1)
    type: ToolValueType
    description: str = Field(min_length=1)
    required: bool = False

    enum: list[str] | None = None
    items_type: ToolValueType | None = None


class ToolBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9_]+$",
    )
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    properties: list[ToolProperty] = Field(default_factory=list)

    skip_compilation: bool = False
