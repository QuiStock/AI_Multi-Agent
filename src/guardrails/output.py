from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Literal

from .config import GuardrailConfig, OutputGuardrailResult
from .pii import restore_pii_placeholders

CONTROLLED_OUTPUT_RESPONSE = (
    "Não foi possível liberar essa resposta. "
    "Tente novamente ou entre em contato com o suporte."
)


def _controlled_correction(
    reason_code: str,
    reason: str,
    *,
    violations: list[str] | None = None,
) -> OutputGuardrailResult:
    """Approve the turn with a controlled replacement response."""
    return _result(
        reason_code,
        reason,
        status="passed",
        violations=violations,
        sanitized_content=CONTROLLED_OUTPUT_RESPONSE,
    )


OutputSource = Literal["faq", "compiled"]


_EMOJI_PATTERN = re.compile("[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff\u2600-\u27bf]")


_UNSUPPORTED_COMMERCIAL_CLAIMS = (
    "pedido enviado",
    "compra concluída",
    "promoção ativada",
    "entrega confirmada",
    "pedido processado",
)


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


def _result(
    reason_code: str,
    reason: str,
    *,
    status: Literal["passed"],
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
        return _controlled_correction(
            "invalid_output_type",
            "A resposta não possui formato textual válido.",
        )

    if not config.enabled:
        return _result(
            "disabled",
            "Guardrail de saída desabilitado.",
            status="passed",
            sanitized_content=content,
        )

    if len(content) > config.max_output_chars:
        return _controlled_correction(
            "response_too_long",
            "A resposta excede o limite permitido.",
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

    return _controlled_correction(
        "empty_response" if "empty_response" in violations else "invalid_markdown",
        "A resposta não atende ao formato mínimo permitido.",
        violations=violations,
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

    return _controlled_correction(
        "missing_sources",
        "A resposta do FAQ não possui fontes suficientes.",
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

    return _controlled_correction(
        "unsupported_commercial_claim",
        "A resposta afirma uma operação que não pertence ao escopo do Quistock.",
    )


def validate_output(
    content: str,
    *,
    config: GuardrailConfig | None = None,
    source: OutputSource,
    references: Sequence[str] = (),
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

    return _result(
        "approved",
        "A resposta passou pela validação.",
        status="passed",
        sanitized_content=sanitized_result,
    )


def output_guardrail_node(
    state: Mapping[str, object],
    *,
    guardrail_config: GuardrailConfig | None = None,
    source: OutputSource,
) -> dict[str, object]:
    response = state.get("response_draft")
    if not isinstance(response, Mapping):
        response = state.get("final_response")

    result: OutputGuardrailResult
    content: str

    if not isinstance(response, Mapping):
        result = _controlled_correction(
            "empty_response",
            "Nenhuma resposta foi disponibilizada para validação.",
            violations=["empty_response"],
        )
        content = CONTROLLED_OUTPUT_RESPONSE
        response = {
            "content": content,
            "citations": [],
            "status": "draft",
        }
    else:
        raw_agent_results = state.get("agent_results")
        judge = (
            raw_agent_results.get("judge")
            if isinstance(raw_agent_results, Mapping)
            else None
        )

        if source == "compiled" and not isinstance(judge, Mapping):
            result = _controlled_correction(
                "judge_missing",
                "A resposta não possui validação do agente juiz.",
                violations=["judge_missing"],
            )
            content = CONTROLLED_OUTPUT_RESPONSE
        elif (
            source == "compiled"
            and isinstance(judge, Mapping)
            and judge.get("status") != "approved"
        ):
            result = _controlled_correction(
                "judge_not_approved",
                "A resposta não foi aprovada pelas evidências disponíveis.",
                violations=["judge_not_approved"],
            )
            content = CONTROLLED_OUTPUT_RESPONSE
        else:
            raw_content = response.get("content")
            if not isinstance(raw_content, str):
                result = _controlled_correction(
                    "invalid_output_type",
                    "A resposta final não possui conteúdo textual.",
                )
                content = CONTROLLED_OUTPUT_RESPONSE
            else:
                raw_evidences = state.get("evidences", [])
                references = (
                    [
                        item["content"]
                        for item in raw_evidences
                        if isinstance(item, Mapping)
                        and isinstance(item.get("content"), str)
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

                result = validate_output(
                    raw_content,
                    config=guardrail_config,
                    source=source,
                    references=references,
                )
                sanitized_content = result.get("sanitized_content")
                content = (
                    sanitized_content
                    if isinstance(sanitized_content, str)
                    else raw_content
                )

    raw_pii_map = state.get("pii_map", {})
    pii_map = (
        {str(key): str(value) for key, value in raw_pii_map.items()}
        if isinstance(raw_pii_map, Mapping)
        else {}
    )
    restored_content = restore_pii_placeholders(content, pii_map)
    response_draft = {
        **response,
        "content": restored_content,
        "status": "draft",
    }

    return {
        "output_guardrail": result,
        "response_draft": response_draft,
        "final_response": {
            "content": restored_content,
            "status": "success",
        },
        "status": "in_progress",
    }


def create_output_guardrail_node(
    *,
    source: OutputSource,
    guardrail_config: GuardrailConfig | None = None,
) -> Callable[[Mapping[str, object]], dict[str, object]]:
    return partial(
        output_guardrail_node,
        source=source,
        guardrail_config=guardrail_config,
    )
