from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .config import GuardrailConfig, GuardrailResult
from .input import SemanticCategory, validate_input
from .output import OutputSource, SupportStatus, validate_output


class GuardrailPipeline:
    def __init__(
        self,
        config: GuardrailConfig | None = None,
        *,
        classifier: Callable[[str], SemanticCategory] | None = None,
        evaluator: Callable[[str, list[str]], SupportStatus] | None = None,
    ) -> None:
        self.config = config or GuardrailConfig()
        self.classifier = classifier
        self.evaluator = evaluator

    def check_input(
        self,
        state: Mapping[str, Any],
    ) -> GuardrailResult:
        return validate_input(
            state,
            config=self.config,
            classifier=self.classifier,
        )

    def check_output(
        self,
        content: str,
        *,
        source: OutputSource,
        references: Sequence[str] = (),
    ) -> GuardrailResult:
        return validate_output(
            content,
            config=self.config,
            source=source,
            references=references,
            evaluator=self.evaluator,
        )