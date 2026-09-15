"""Input guardrail boundary used before routing.

The original user message is never returned by this module. When the input is
allowed, downstream nodes receive only the sanitized representation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal, cast

from langchain_core.messages import HumanMessage

from src.context.state import GraphState, GuardrailReasonCode, InputGuardrail
from src.llm_factory import llm_fast

CONTROLLED_INPUT_RESPONSE = (
    "Não posso processar essa solicitação. "
    "Posso ajudar com informações documentadas sobre os processos da organização."
)

MAX_INPUT_LENGTH = 4000

SemanticCategory = Literal[
    "APROVADO",
    "OFENSIVO",
    "PERIGOSO",
    "ILICITO",
    "POLITICA_GOVERNAMENTAL",
]

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("CNPJ", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    (
        "EMAIL",
        re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+\b"),
    ),
    (
        "TELEFONE",
        re.compile(r"(?<!\d)\(?\d{2}\)?\s?\d{4,5}-?\d{4}(?!\d)"),
    ),
    (
        "CARTAO",
        re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"),
    ),
    (
        "CREDENCIAL",
        re.compile(r"(?i)\b(?:api[_ -]?key|token|senha|password|secret)\s*[:=]\s*\S+"),
    ),
)

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
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

_SEMANTIC_PROMPT = """Você é um classificador de segurança.
Classifique a mensagem sanitizada em uma única categoria:
APROVADO, OFENSIVO, PERIGOSO, ILICITO ou POLITICA_GOVERNAMENTAL.
Responda somente no formato: CATEGORIA: <categoria>

Mensagem: {message}
"""

_BLOCKED_CATEGORIES: dict[SemanticCategory, tuple[GuardrailReasonCode, str]] = {
    "OFENSIVO": (
        "offensive_content",
        "A mensagem foi classificada como conteúdo ofensivo.",
    ),
    "PERIGOSO": (
        "dangerous_request",
        "A mensagem foi classificada como pedido perigoso.",
    ),
    "ILICITO": (
        "illegal_request",
        "A mensagem foi classificada como pedido ilícito.",
    ),
    "POLITICA_GOVERNAMENTAL": (
        "government_politics",
        "A mensagem trata de política governamental.",
    ),
}


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)


def _blocked(
    reason_code: GuardrailReasonCode,
    reason: str,
    redactions: list[str],
) -> InputGuardrail:
    return {
        "status": "blocked",
        "reason_code": reason_code,
        "reason": reason,
        "redactions": redactions,
        "history_marker": f"[GUARDRAIL_BLOCKED: {reason_code}]",
    }


def _redact_sensitive_data(text: str) -> tuple[str, list[str]]:
    redactions: list[str] = []
    sanitized = text
    for kind, pattern in _PII_PATTERNS:
        if pattern.search(sanitized):
            sanitized = pattern.sub(f"[DADO_SENSIVEL_{kind}]", sanitized)
            redactions.append(kind)
    return sanitized, redactions


def _classify_semantically(message: str) -> SemanticCategory:
    result = llm_fast.invoke(_SEMANTIC_PROMPT.format(message=message))
    content = _content_to_text(getattr(result, "content", result))
    for line in content.splitlines():
        if line.strip().upper().startswith("CATEGORIA:"):
            category = line.split(":", 1)[1].strip().upper()
            if category in {"APROVADO", *(_BLOCKED_CATEGORIES.keys())}:
                return cast(SemanticCategory, category)
    raise ValueError("Classificação semântica inválida.")


def validate_input(
    state: GraphState,
    *,
    classifier: Callable[[str], SemanticCategory] = _classify_semantically,
) -> InputGuardrail:
    """Validate and sanitize input before any specialized agent is called."""

    messages = state.get("messages", [])
    latest_human = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )
    if latest_human is None or not _content_to_text(latest_human.content).strip():
        return _blocked(
            "empty_message",
            "A mensagem do usuário está vazia.",
            [],
        )

    text = _content_to_text(latest_human.content).strip()
    if len(text) > MAX_INPUT_LENGTH:
        return _blocked(
            "message_too_long",
            "A mensagem excede o limite permitido.",
            [],
        )

    sanitized, redactions = _redact_sensitive_data(text)

    if any(pattern.search(sanitized) for pattern in _INJECTION_PATTERNS):
        return _blocked(
            "prompt_injection",
            "A mensagem contém uma tentativa de manipular as instruções.",
            redactions,
        )

    lowered = sanitized.lower()
    if any(keyword in lowered for keyword in _INTERNAL_DATA_KEYWORDS):
        return _blocked(
            "access_internal_data",
            "A mensagem solicita informações internas do sistema.",
            redactions,
        )

    if any(pattern.search(sanitized) for pattern in _GOVERNMENT_POLITICS_PATTERNS):
        return _blocked(
            "government_politics",
            "A mensagem trata de política governamental.",
            redactions,
        )

    try:
        category = classifier(sanitized)
    except Exception:
        return _blocked(
            "classifier_unavailable",
            "Não foi possível concluir a classificação de segurança.",
            redactions,
        )

    if category in _BLOCKED_CATEGORIES:
        reason_code, reason = _BLOCKED_CATEGORIES[category]
        return _blocked(reason_code, reason, redactions)

    return {
        "status": "passed",
        "reason_code": "approved",
        "reason": "Entrada aprovada pelo guardrail.",
        "redactions": redactions,
        "sanitized_message": sanitized,
    }


def input_guardrail_node(
    state: GraphState,
    validator: Callable[[GraphState], InputGuardrail] = validate_input,
) -> dict[str, Any]:
    """Run the guardrail and write only its result to shared state."""

    result = validator(state)
    return {
        "input_guardrail": result,
        "status": "in_progress" if result["status"] == "passed" else "completed",
    }
