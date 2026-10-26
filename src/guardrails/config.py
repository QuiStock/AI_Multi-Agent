from dataclasses import dataclass
from typing import Literal, TypedDict

GuardrailStatus = Literal["passed", "blocked"]


class InputGuardrailResult(TypedDict, total=False):
    status: GuardrailStatus
    reason_code: str
    reason: str
    redactions: list[str]
    history_marker: str
    sanitized_message: str


class OutputGuardrailResult(TypedDict, total=False):
    status: Literal["passed"]
    reason_code: str
    reason: str
    violations: list[str]
    sanitized_content: str


@dataclass(frozen=True)
class GuardrailConfig:
    enabled: bool = True

    # Input
    max_input_chars: int = 4_000
    reject_empty_input: bool = True
    redact_sensitive_data: bool = True
    detect_prompt_injection: bool = True
    block_internal_data_requests: bool = True
    block_government_politics: bool = True

    # Output
    max_output_chars: int = 6_000
    remove_emojis: bool = True
    validate_markdown: bool = True
    block_unsupported_commercial_claims: bool = True
