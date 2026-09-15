from dataclasses import dataclass
from typing import Literal, TypedDict

GuardrailStatus = Literal["passed", "blocked"]


class GuardrailResult(TypedDict, total=False):
    status: GuardrailStatus
    reason_code: str
    reason: str
    redactions: list[str]
    violations: list[str]
    history_marker: str
    sanitized_message: str
    sanitized_content: str


@dataclass(frozen=True)
class GuardrailConfig:
    enabled: bool = True
    fail_closed: bool = True

    # Input
    max_input_chars: int = 4_000
    reject_empty_input: bool = True
    redact_sensitive_data: bool = True
    detect_prompt_injection: bool = True
    block_internal_data_requests: bool = True
    block_government_politics: bool = True
    classify_semantically: bool = True

    # Output
    max_output_chars: int = 6_000
    remove_emojis: bool = True
    validate_markdown: bool = True
    require_sources_for_faq: bool = True
    evaluate_compiled_support: bool = True
    block_unsupported_commercial_claims: bool = True

    timeout_ms: int = 1_500