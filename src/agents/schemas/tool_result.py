from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, Self, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataT = TypeVar("DataT")

JsonScalar: TypeAlias = str | int | float | bool | None

ToolErrorCategory: TypeAlias = Literal[
    "validation",
    "authorization",
    "not_found",
    "dependency",
    "timeout",
    "internal",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class ToolStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


ToolNextStep: TypeAlias = Literal[
    "continue",
    "direct_response",
    "clarification",
    "controlled_error",
]


class ToolEvidence(ContractModel):
    evidence_id: str = Field(
        min_length=1,
        max_length=120,
    )

    source_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    source_id: str = Field(
        min_length=1,
        max_length=240,
    )

    content: str = Field(
        min_length=1,
        max_length=12_000,
    )

    metadata: dict[str, JsonScalar] = Field(
        default_factory=dict,
    )


class ToolError(ContractModel):
    code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    category: ToolErrorCategory

    message: str = Field(
        min_length=1,
        max_length=500,
    )

    retryable: bool = False

    details: dict[str, JsonScalar] = Field(
        default_factory=dict,
    )


class ToolMetadata(ContractModel):
    tool_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    tool_version: str = Field(
        pattern=r"^\d+\.\d+\.\d+$",
    )

    tool_call_id: str = Field(
        min_length=1,
        max_length=160,
    )

    trace_id: str = Field(
        min_length=1,
        max_length=160,
    )

    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def validate_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must contain timezone information",
            )

        return value


class ToolResult(ContractModel, Generic[DataT]):
    schema_version: Literal["1.0"] = "1.0"

    status: ToolStatus
    data: DataT | None = None
    evidence: list[ToolEvidence] = Field(
        default_factory=list,
        max_length=64,
    )
    error: ToolError | None = None
    meta: ToolMetadata

    @model_validator(mode="after")
    def validate_result_invariants(self) -> Self:
        if self.status is ToolStatus.SUCCESS and self.error is not None:
            raise ValueError("A successful result cannot contain an error")
        if self.status is ToolStatus.PARTIAL and self.data is None:
            raise ValueError("A partial result must contain partial data")
        if self.status is ToolStatus.ERROR:
            if self.error is None:
                raise ValueError("An error result must contain an error object")
            if self.data is not None or self.evidence:
                raise ValueError(
                    "An error result cannot contain data or evidence",
                )
        return self
