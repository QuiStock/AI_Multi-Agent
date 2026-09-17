from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from .config import (
    GuardrailConfig,
    OutputGuardrailResult,
    SupportValidationResult,
)

CONTROLLED_OUTPUT_RESPONSE = (
    "Não foi possível liberar essa resposta. "
    "Tente novamente ou entre em contato com o suporte."
)


OutputSource = Literal["faq", "compiled"]
SupportStatus = Literal["supported", "unsupported"]


_EMOJI_PATTERN = re.compile("[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff\u2600-\u27bf]")


_UNSUPPORTED_COMMERCIAL_CLAIMS = (
    "pedido enviado",
    "compra concluída",
    "promoção ativada",
    "entrega confirmada",
    "pedido processado",
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
    from src.llm_factory import get_structured_model

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


def _result(
    reason_code: str,
    reason: str,
    *,
    status: Literal["passed", "blocked"],
    violations: list[str] | None = None,
    sanitized_content: str | None = None,
) -> OutputGuardrailResult:
    result: OutputGuardrailResult = {
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "violations": violations or [],
    }

    if sanitized_content is not None:
        result["sanitized_content"] = sanitized_content

    return result


def _initial_output_result(
    content: object,
    config: GuardrailConfig,
) -> OutputGuardrailResult | None:
    if not isinstance(content, str):
        return _result(
            "invalid_output_type",
            "A resposta não possui formato textual válido.",
            status="blocked",
        )

    if not config.enabled:
        return _result(
            "disabled",
            "Guardrail de saída desabilitado.",
            status="passed",
            sanitized_content=content,
        )

    if len(content) > config.max_output_chars:
        return _result(
            "response_too_long",
            "A resposta excede o limite permitido.",
            status="blocked",
        )

    return None


def _sanitize_output(
    content: str,
    config: GuardrailConfig,
) -> tuple[str, str | None]:
    if not config.remove_emojis:
        return content, None

    sanitized, emoji_removed = _remove_emojis(content)
    return sanitized, sanitized if emoji_removed else None


def _markdown_result(
    sanitized: str,
    sanitized_result: str | None,
    config: GuardrailConfig,
) -> OutputGuardrailResult | None:
    if not config.validate_markdown:
        return None

    violations = _markdown_violations(sanitized)
    if not violations:
        return None

    return _result(
        "empty_response" if "empty_response" in violations else "invalid_markdown",
        "A resposta não atende ao formato mínimo permitido.",
        status="blocked",
        violations=violations,
        sanitized_content=sanitized_result,
    )


def _missing_sources_result(
    *,
    source: OutputSource,
    references: Sequence[str],
    sanitized_result: str | None,
    config: GuardrailConfig,
) -> OutputGuardrailResult | None:
    if source != "faq" or not config.require_sources_for_faq or references:
        return None

    return _result(
        "missing_sources",
        "A resposta do FAQ não possui fontes suficientes.",
        status="blocked",
        sanitized_content=sanitized_result,
    )


def _commercial_claim_result(
    sanitized: str,
    sanitized_result: str | None,
    config: GuardrailConfig,
) -> OutputGuardrailResult | None:
    if not config.block_unsupported_commercial_claims:
        return None

    lowered = sanitized.casefold()
    if not any(claim in lowered for claim in _UNSUPPORTED_COMMERCIAL_CLAIMS):
        return None

    return _result(
        "unsupported_commercial_claim",
        "A resposta afirma uma operação que não pertence ao escopo do Quistock.",
        status="blocked",
        sanitized_content=sanitized_result,
    )


def _compiled_support_result(
    sanitized: str,
    references: Sequence[str],
    sanitized_result: str | None,
    evaluator: Callable[[str, list[str]], SupportStatus] | None,
) -> OutputGuardrailResult | None:
    if evaluator is None:
        return _result(
            "validator_unavailable",
            "Não foi possível validar o suporte da resposta.",
            status="blocked",
            violations=["support_validation_failed"],
            sanitized_content=sanitized_result,
        )

    try:
        support = evaluator(sanitized, list(references))
    except Exception:
        return _result(
            "validator_unavailable",
            "Não foi possível validar o suporte da resposta.",
            status="blocked",
            violations=["support_validation_failed"],
            sanitized_content=sanitized_result,
        )

    if support == "unsupported":
        return _result(
            "unsupported_content",
            "A resposta contém conteúdo não sustentado pelos materiais fornecidos.",
            status="blocked",
            violations=["unsupported_content"],
            sanitized_content=sanitized_result,
        )

    if support != "supported":
        return _result(
            "validator_unavailable",
            "A validação não retornou uma classificação permitida.",
            status="blocked",
            violations=["invalid_support_status"],
            sanitized_content=sanitized_result,
        )

    return None


def validate_output(
    content: str,
    *,
    config: GuardrailConfig | None = None,
    source: OutputSource,
    references: Sequence[str] = (),
    evaluator: Callable[[str, list[str]], SupportStatus] | None = None,
) -> OutputGuardrailResult:
    config = config or GuardrailConfig()

    initial_result = _initial_output_result(content, config)
    if initial_result is not None:
        return initial_result

    sanitized, sanitized_result = _sanitize_output(content, config)

    markdown_result = _markdown_result(
        sanitized,
        sanitized_result,
        config,
    )
    if markdown_result is not None:
        return markdown_result

    sources_result = _missing_sources_result(
        source=source,
        references=references,
        sanitized_result=sanitized_result,
        config=config,
    )
    if sources_result is not None:
        return sources_result

    commercial_claim_result = _commercial_claim_result(
        sanitized,
        sanitized_result,
        config,
    )
    if commercial_claim_result is not None:
        return commercial_claim_result

    if source == "compiled" and config.evaluate_compiled_support:
        support_result = _compiled_support_result(
            sanitized,
            references,
            sanitized_result,
            evaluator,
        )
        if support_result is not None:
            return support_result

    return _result(
        "approved",
        "A resposta passou pela validação.",
        status="passed",
        sanitized_content=sanitized_result,
    )


def output_guardrail_node(
    state: Mapping[str, object],
    *,
    config: GuardrailConfig | None = None,
    source: OutputSource,
    evaluator: Callable[[str, list[str]], SupportStatus] | None = None,
) -> dict[str, object]:
    response_key = "response_draft"
    response = state.get(response_key)

    if not isinstance(response, Mapping):
        response_key = "final_response"
        response = state.get(response_key)

    if not isinstance(response, Mapping):
        result = _result(
            "empty_response",
            "Nenhuma resposta foi disponibilizada para validação.",
            status="blocked",
            violations=["empty_response"],
        )

        return {
            "output_guardrail": result,
            "status": "completed",
        }

    raw_agent_results = state.get("agent_results")
    judge = (
        raw_agent_results.get("judge")
        if isinstance(raw_agent_results, Mapping)
        else None
    )

    if source == "compiled":
        if not isinstance(judge, Mapping):
            result = _result(
                "judge_missing",
                "A resposta não possui validação do agente juiz.",
                status="blocked",
                violations=["judge_missing"],
            )

            return {
                "output_guardrail": result,
                "status": "completed",
            }

        if judge.get("status") != "approved":
            result = _result(
                "judge_not_approved",
                "A resposta não foi aprovada pelas evidências disponíveis.",
                status="blocked",
                violations=["judge_not_approved"],
            )

            return {
                "output_guardrail": result,
                "status": "completed",
            }

    content = response.get("content")

    if not isinstance(content, str):
        result = _result(
            "invalid_output_type",
            "A resposta final não possui conteúdo textual.",
            status="blocked",
        )

        return {
            "output_guardrail": result,
            "status": "completed",
        }

    raw_evidences = state.get("evidences", [])
    references = (
        [
            item["content"]
            for item in raw_evidences
            if isinstance(item, Mapping) and isinstance(item.get("content"), str)
        ]
        if isinstance(raw_evidences, list)
        else []
    )

    if not references:
        raw_results = state.get("agent_results", {})
        references = (
            [
                value[key]
                for value in raw_results.values()
                if isinstance(value, Mapping)
                for key in ("answer", "content")
                if isinstance(value.get(key), str)
            ]
            if isinstance(raw_results, Mapping)
            else []
        )

    validation_config = config or GuardrailConfig()

    if isinstance(judge, Mapping) and judge.get("status") == "approved":
        validation_config = replace(
            validation_config,
            evaluate_compiled_support=False,
        )

    result = validate_output(
        content,
        config=validation_config,
        source=source,
        references=references,
        evaluator=evaluator,
    )

    update: dict[str, object] = {
        "output_guardrail": result,
        "status": ("in_progress" if result["status"] == "passed" else "completed"),
    }

    sanitized_content = result.get("sanitized_content")

    if isinstance(sanitized_content, str):
        update[response_key] = {
            **response,
            "content": sanitized_content,
        }

    return update


def create_output_guardrail_node(
    *,
    source: OutputSource,
    model: Any | None = None,
    config: GuardrailConfig | None = None,
) -> Callable[[Mapping[str, object]], dict[str, object]]:
    evaluator: Callable[[str, list[str]], SupportStatus] | None = None

    if source == "compiled":
        evaluator = partial(evaluate_compiled_output, model=model)

    return partial(
        output_guardrail_node,
        source=source,
        evaluator=evaluator,
        config=config,
    )
