from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.messages import HumanMessage

from .config import (
    GuardrailConfig,
    InputGuardrailResult,
)
from .pii import redact_sensitive_data

CONTROLLED_INPUT_RESPONSE = (
    "Não posso processar essa solicitação. "
    "Posso ajudar com informações documentadas sobre os processos da organização."
)

_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(as\s+)?instru[çc][oõ]es",
        r"ignore\s+previous\s+instructions",
        r"forget\s+your\s+instructions",
        r"you\s+are\s+now\s+",
        r"act\s+as\s+(if\s+)?",
        r"pretend\s+(you\s+are|to\s+be)",
        r"jailbreak",
        r"dan\s+mode",
        r"modo\s+irrestrito",
        r"system\s*prompt",
        r"<\s*system\s*>",
        r"\[INST\]",
        r"###\s*instruction",
        r"override\s+(your\s+)?instructions",
        r"desconsider[ea]\s+(suas\s+)?instru[çc][oõ]es",
        r"ignore\s+(as\s+|suas\s+)?regras",
        r"desconsider[ea]\s+(as\s+|suas\s+)?regras",
    )
)


_INTERNAL_DATA_KEYWORDS = (
    "prompt do sistema",
    "system prompt",
    "suas instruções",
    "your instructions",
    "variável de ambiente",
    "chave de api",
    "api key",
    "senha do sistema",
    "token de acesso",
    "banco de dados interno",
    "tabela interna",
    "dados de outros clientes",
    "lista de clientes",
    "credenciais",
    "sql",
    "schema",
    "query",
    "consulta sql",
    "select ",
    "tabela suggestion",
    "tabela product",
    "user_account",
    "user_store",
)


_GOVERNMENT_POLITICS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"pol[ií]tica\s+(governamental|p[uú]blica)",
        r"elei[cç][aã]o|elei[cç][oõ]es",
        r"partido\s+pol[ií]tico",
        r"(presidente|governador|prefeito|deputado|senador|vereador)",
        r"governo\s+(atual|federal|estadual|municipal)",
        r"minist[eé]rio|congresso\s+nacional",
    )
)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)

    return str(content)


def _latest_human_message(state: Mapping[str, Any]) -> str | None:
    messages = state.get("messages", [])

    for message in reversed(messages):
        message_type = getattr(message, "type", None)

        if isinstance(message, Mapping):
            message_type = message.get("type") or message.get("role")

        if message_type not in {"human", "user"}:
            continue

        content = (
            message.get("content")
            if isinstance(message, Mapping)
            else getattr(message, "content", message)
        )

        return _content_to_text(content).strip()

    return None


def _blocked(
    reason_code: str,
    reason: str,
    redactions: list[str] | None = None,
) -> InputGuardrailResult:
    return {
        "status": "blocked",
        "reason_code": reason_code,
        "reason": reason,
        "redactions": redactions or [],
        "history_marker": f"[GUARDRAIL_BLOCKED: {reason_code}]",
    }


def _initial_input_result(
    text: str | None,
    config: GuardrailConfig,
    original_length: int | None = None,
) -> InputGuardrailResult | None:
    if text is None or (config.reject_empty_input and not text.strip()):
        return _blocked(
            "empty_message",
            "A mensagem do usuário está vazia.",
        )

    if not config.enabled:
        return {
            "status": "passed",
            "reason_code": "disabled",
            "reason": "Guardrail de entrada desabilitado.",
            "redactions": [],
            "sanitized_message": text,
        }

    if (original_length if original_length is not None else len(text)) > (
        config.max_input_chars
    ):
        return _blocked(
            "message_too_long",
            "A mensagem excede o limite permitido.",
        )

    return None


def _static_input_result(
    sanitized: str,
    redactions: list[str],
    config: GuardrailConfig,
) -> InputGuardrailResult | None:
    if config.detect_prompt_injection and any(
        pattern.search(sanitized) for pattern in _INJECTION_PATTERNS
    ):
        return _blocked(
            "prompt_injection",
            "A mensagem contém uma tentativa de manipular as instruções.",
            redactions,
        )

    lowered = sanitized.casefold()

    if config.block_internal_data_requests and any(
        keyword in lowered for keyword in _INTERNAL_DATA_KEYWORDS
    ):
        return _blocked(
            "access_internal_data",
            "A mensagem solicita informações internas do sistema.",
            redactions,
        )

    if config.block_government_politics and any(
        pattern.search(sanitized) for pattern in _GOVERNMENT_POLITICS_PATTERNS
    ):
        return _blocked(
            "government_politics",
            "A mensagem trata de política governamental.",
            redactions,
        )

    return None


def validate_input(
    state: Mapping[str, Any],
    *,
    config: GuardrailConfig | None = None,
    already_sanitized: bool = False,
    original_length: int | None = None,
) -> InputGuardrailResult:
    config = config or GuardrailConfig()
    text = _latest_human_message(state)

    initial_result = _initial_input_result(text, config, original_length)
    if initial_result is not None:
        return initial_result

    assert text is not None

    sanitized = text
    redactions: list[str] = []

    if config.redact_sensitive_data and not already_sanitized:
        sanitized, redactions, _ = redact_sensitive_data(text)
    elif already_sanitized:
        redactions = list(
            dict.fromkeys(
                re.findall(
                    r"\[DADO_SENSIVEL_([A-Z]+)(?:_[A-Za-z0-9-]+)?_\d+\]",
                    text,
                )
            )
        )

    static_result = _static_input_result(
        sanitized,
        redactions,
        config,
    )
    if static_result is not None:
        return static_result

    return {
        "status": "passed",
        "reason_code": "approved",
        "reason": "Entrada aprovada pelo guardrail.",
        "redactions": redactions,
        "sanitized_message": sanitized,
    }


def input_guardrail_node(
    state: Mapping[str, Any],
    *,
    validator: Callable[[Mapping[str, Any]], InputGuardrailResult] | None = None,
    guardrail_config: GuardrailConfig | None = None,
) -> dict[str, Any]:
    request = state.get("request")
    already_sanitized = (
        isinstance(request, Mapping)
        and request.get("pii_redacted_before_graph") is True
    )
    original_length_value = (
        request.get("original_message_length") if isinstance(request, Mapping) else None
    )
    original_length = (
        original_length_value if isinstance(original_length_value, int) else None
    )
    result = (
        validator(state)
        if validator is not None
        else validate_input(
            state,
            config=guardrail_config,
            already_sanitized=already_sanitized,
            original_length=original_length,
        )
    )

    # Sanitized text and original PII mappings are transient guardrail output.
    # Only the sanitized message is written into the shared messages channel.
    sanitized_message = result.get("sanitized_message")
    public_result = {
        key: value
        for key, value in result.items()
        if key not in {"sanitized_message", "pii_map"}
    }
    update: dict[str, Any] = {
        "input_guardrail": public_result,
        "status": ("in_progress" if result["status"] == "passed" else "completed"),
    }

    messages = state.get("messages", [])
    if isinstance(sanitized_message, str) and sanitized_message.strip():
        latest_human = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, HumanMessage)
            ),
            None,
        )
        if latest_human is None:
            raise ValueError("A mensagem do usuário não foi encontrada no estado")
        update["messages"] = [
            HumanMessage(content=sanitized_message, id=latest_human.id)
        ]

    return update
