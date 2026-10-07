from collections.abc import Mapping, Sequence
from typing import Any

from .config import (
    GuardrailConfig,
    InputGuardrailResult,
    OutputGuardrailResult,
)
from .input import validate_input
from .output import OutputSource, validate_output


class GuardrailPipeline:
    def __init__(
        self,
        config: GuardrailConfig | None = None,
    ) -> None:
        self.config = config or GuardrailConfig()

    def check_input(
        self,
        state: Mapping[str, Any],
    ) -> InputGuardrailResult:
        return validate_input(
            state,
            config=self.config,
        )

    def check_output(
        self,
        content: str,
        *,
        source: OutputSource,
        references: Sequence[str] = (),
    ) -> OutputGuardrailResult:
        return validate_output(
            content,
            config=self.config,
            source=source,
            references=references,
        )
