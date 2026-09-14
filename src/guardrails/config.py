from dataclasses import dataclass
from typing import Literal


GuardRailStatus = Literal[
    "ALLOW",
    "BLOCK",
    "FALLBACK",
]

@dataclass(frozen=True)
class GuardrailConfig:
    enabled: bool = True
    fail_closed: bool = True

    max_input_chars: int = 4_000
    reject_empty_input: bool = True
    detect_prompt_injection: bool = True

    max_output_chars: int = 6_000
    require_sources_for_faq: bool = True
    block_unsupported_comercial_claims: bool = True

    timeout_ms: int = 1_500

@dataclass(frozen=True)
class GuardrailResult:
    status: GuardRailStatus
    code: str
    message: str
    sanitized_value: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "ALLOW"