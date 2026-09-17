from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    Self,
    TypeAlias,
    TypeVar,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DataT = TypeVar("DataT")

JsonScalar: TypeAlias = str | int | float | bool | None

JsonPointer = Annotated[
    str,
    Field(
        min_length=1,
        max_length=240,
        pattern=r"^/",
    ),
]

ConstraintText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=500,
    ),
]

ResponseFormat: TypeAlias = Literal["plain", "markdown"]

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


class ResponseContent(ContractModel):
    text: str = Field(
        min_length=1,
        max_length=6_000,
    )
    format: ResponseFormat = "plain"


class DirectResponse(ContractModel):
    mode: Literal["direct"] = "direct"
    content: ResponseContent


class ComposeResponse(ContractModel):
    mode: Literal["compose"] = "compose"

    intent: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    must_include: list[JsonPointer] = Field(
        default_factory=list,
        max_length=32,
    )

    constraints: list[ConstraintText] = Field(
        default_factory=list,
        max_length=16,
    )

    @field_validator(
        "must_include",
        "constraints",
    )
    @classmethod
    def validate_unique_items(
        cls,
        values: list[str],
    ) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError(
                "The list cannot contain duplicated items",
            )

        return values


class NoResponse(ContractModel):
    mode: Literal["none"] = "none"


ToolResponse: TypeAlias = Annotated[
    DirectResponse | ComposeResponse | NoResponse,
    Field(discriminator="mode"),
]


class NavigateAction(ContractModel):
    type: Literal["navigate"] = "navigate"

    target: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    label: str = Field(
        min_length=1,
        max_length=80,
    )

    params: dict[str, JsonScalar] = Field(
        default_factory=dict,
    )


ToolAction: TypeAlias = NavigateAction


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


class ToolWarning(ContractModel):
    code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    message: str = Field(
        min_length=1,
        max_length=500,
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


def _json_pointer_exists(
    document: Any,
    pointer: str,
) -> bool:
    current = document

    if isinstance(current, BaseModel):
        current = current.model_dump(mode="json")

    for encoded_part in pointer[1:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")

        if isinstance(current, BaseModel):
            current = current.model_dump(mode="json")

        if isinstance(current, Mapping):
            if part not in current:
                return False

            current = current[part]
            continue

        if isinstance(current, Sequence) and not isinstance(
            current,
            (str, bytes, bytearray),
        ):
            try:
                index = int(part)
            except ValueError:
                return False

            if index < 0 or index >= len(current):
                return False

            current = current[index]
            continue

        return False

    return True


class ToolResult(ContractModel, Generic[DataT]):
    schema_version: Literal["1.0"] = "1.0"

    status: ToolStatus
    response: ToolResponse

    data: DataT | None = None

    actions: list[ToolAction] = Field(
        default_factory=list,
        max_length=16,
    )

    evidence: list[ToolEvidence] = Field(
        default_factory=list,
        max_length=64,
    )

    warnings: list[ToolWarning] = Field(
        default_factory=list,
        max_length=32,
    )

    error: ToolError | None = None
    meta: ToolMetadata

    @model_validator(mode="after")
    def validate_result_invariants(self) -> Self:
        self._validate_status_invariants()
        self._validate_response_invariants()
        return self

    def _validate_status_invariants(self) -> None:
        if self.status is ToolStatus.SUCCESS:
            self._validate_success_invariants()
        elif self.status is ToolStatus.ERROR:
            self._validate_error_invariants()
        else:
            self._validate_partial_invariants()

    def _validate_success_invariants(self) -> None:
        if self.error is not None:
            raise ValueError(
                "A successful result cannot contain an error",
            )

        if isinstance(self.response, NoResponse):
            raise ValueError(
                "A successful result must expose a response",
            )

    def _validate_error_invariants(self) -> None:
        if self.error is None:
            raise ValueError(
                "An error result must contain an error object",
            )

        if self.data is not None:
            raise ValueError(
                "An error result cannot contain data",
            )

        if isinstance(self.response, ComposeResponse):
            raise ValueError(
                "Technical errors cannot delegate response composition",
            )

        if self.actions:
            raise ValueError(
                "An error result cannot expose navigation actions",
            )

    def _validate_partial_invariants(self) -> None:
        if self.data is None:
            raise ValueError(
                "A partial result must contain partial data",
            )

        if not self.warnings and self.error is None:
            raise ValueError(
                "A partial result must explain why it is partial",
            )

        if isinstance(self.response, NoResponse):
            raise ValueError(
                "A partial result must expose a response",
            )

    def _validate_response_invariants(self) -> None:
        if not isinstance(self.response, ComposeResponse):
            return

        if self.data is None:
            raise ValueError(
                "A compose response must contain structured data",
            )

        missing_pointers = [
            pointer
            for pointer in self.response.must_include
            if not _json_pointer_exists(
                self.data,
                pointer,
            )
        ]

        if missing_pointers:
            missing = ", ".join(missing_pointers)
            raise ValueError(
                f"must_include references missing data: {missing}",
            )
