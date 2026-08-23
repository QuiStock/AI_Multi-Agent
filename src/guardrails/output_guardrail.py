"""Output validation before a response is released to the user."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from src.context.schemas import SupportValidationResult
from src.context.state import (
    GraphState,
    OutputGuardrail,
    OutputGuardrailReasonCode,
)
from src.llm_factory import get_structured_model

OutputSource = Literal["faq", "compiled"]
SupportStatus = Literal["supported", "unsupported"]
SupportEvaluator = Callable[[str, list[str]], SupportStatus]

CONTROLLED_OUTPUT_RESPONSE = (
    "Não foi possível liberar essa resposta. "
    "Tente novamente ou entre em contato com o suporte."
)

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "]"
)

_SUPPORT_SYSTEM_PROMPT = """Você verifica se uma resposta foi sustentada pelos
materiais fornecidos.

Responda somente com uma destas classificações:
- supported: todas as afirmações factuais da resposta estão apoiadas pelos materiais;
- unsupported: existe qualquer afirmação factual nova ou não apoiada.

Permita resumos, reorganização, paráfrases e formatação Markdown.
Não use conhecimento externo, não reescreva a resposta e não avalie regras que
não estejam nos materiais fornecidos.
"""


def _guardrail_result(
    status: Literal["passed", "blocked"],
    reason_code: OutputGuardrailReasonCode,
    reason: str,
    violations: list[str] | None = None,
    sanitized_content: str | None = None,
) -> OutputGuardrail:
    result: OutputGuardrail = {
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "violations": violations or [],
    }
    if sanitized_content is not None:
        result["sanitized_content"] = sanitized_content
    return result


def _remove_emojis(content: str) -> tuple[str, bool]:
    sanitized, count = _EMOJI_PATTERN.subn("", content)
    return sanitized, count > 0


def _markdown_violations(content: str) -> list[str]:
    violations: list[str] = []
    if not content.strip():
        violations.append("empty_response")
    if content.count("`") % 2:
        violations.append("unbalanced_code_delimiter")
    if content.count("**") % 2:
        violations.append("unbalanced_bold_delimiter")
    return violations


def evaluate_compiled_output(
    response: str,
    references: list[str],
    *,
    model: Any | None = None,
) -> SupportStatus:
    """Ask a structured evaluator whether the compiled response is supported."""

    structured_model = model or get_structured_model(
        SupportValidationResult,
        kind="fast",
    )
    materials = json.dumps(references, ensure_ascii=False)
    messages = [
        SystemMessage(content=_SUPPORT_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Materiais fornecidos pelos agentes:\n{materials}\n\n"
                f"Resposta compilada:\n{response}"
            )
        ),
    ]
    result = structured_model.invoke(messages)
    if not isinstance(result, SupportValidationResult):
        result = SupportValidationResult.model_validate(result)
    return result.status


def validate_output(
    content: str,
    *,
    source: OutputSource,
    references: Sequence[str] = (),
    evaluator: SupportEvaluator | None = None,
) -> OutputGuardrail:
    """Validate FAQ formatting or compiled-response support."""

    sanitized_content, emoji_removed = _remove_emojis(content)
    sanitized_result = sanitized_content if emoji_removed else None
    violations = _markdown_violations(sanitized_content)
    if violations:
        reason_code: OutputGuardrailReasonCode = (
            "empty_response" if "empty_response" in violations else "invalid_markdown"
        )
        return _guardrail_result(
            "blocked",
            reason_code,
            "A resposta não atende ao formato mínimo permitido.",
            violations,
            sanitized_result,
        )

    if source == "faq":
        return _guardrail_result(
            "passed",
            "approved",
            "A resposta do FAQ passou pela validação de formato.",
            sanitized_content=sanitized_result,
        )

    support_evaluator = evaluator or evaluate_compiled_output
    try:
        support = support_evaluator(sanitized_content, list(references))
    except (ValidationError, ValueError, RuntimeError):
        return _guardrail_result(
            "blocked",
            "validator_unavailable",
            "Não foi possível validar o suporte da resposta.",
            ["support_validation_failed"],
            sanitized_result,
        )

    if support == "unsupported":
        return _guardrail_result(
            "blocked",
            "unsupported_content",
            "A resposta contém conteúdo não sustentado pelos materiais fornecidos.",
            ["unsupported_content"],
            sanitized_result,
        )

    if support != "supported":
        return _guardrail_result(
            "blocked",
            "validator_unavailable",
            "A validação não retornou uma classificação permitida.",
            ["invalid_support_status"],
            sanitized_result,
        )

    return _guardrail_result(
        "passed",
        "approved",
        "A resposta compilada foi sustentada pelos materiais fornecidos.",
        sanitized_content=sanitized_result,
    )


def output_guardrail_node(
    state: GraphState,
    *,
    source: OutputSource,
    evaluator: SupportEvaluator | None = None,
) -> dict[str, Any]:
    """Validate the current final response without changing the pipeline."""

    response = state.get("final_response")
    if response is None:
        result = _guardrail_result(
            "blocked",
            "empty_response",
            "Nenhuma resposta foi disponibilizada para validação.",
            ["empty_response"],
        )
    else:
        references = [
            output["content"] for output in state.get("agent_outputs", [])
        ]
        result = validate_output(
            response["content"],
            source=source,
            references=references,
            evaluator=evaluator,
        )

    result_update: dict[str, Any] = {
        "output_guardrail": result,
        "status": "completed" if result["status"] == "blocked" else "in_progress",
    }
    sanitized_content = result.get("sanitized_content")
    if sanitized_content is not None and response is not None:
        result_update["final_response"] = {
            **response,
            "content": sanitized_content,
        }
    return result_update


def create_output_guardrail_node(
    *,
    source: OutputSource,
    model: Any | None = None,
) -> Callable[[GraphState], dict[str, Any]]:
    """Create an isolated output guardrail node with optional model injection."""

    evaluator: SupportEvaluator | None = None
    if source == "compiled":
        evaluator = partial(evaluate_compiled_output, model=model)
    return partial(output_guardrail_node, source=source, evaluator=evaluator)


__all__ = [
    "CONTROLLED_OUTPUT_RESPONSE",
    "create_output_guardrail_node",
    "evaluate_compiled_output",
    "output_guardrail_node",
    "validate_output",
]
