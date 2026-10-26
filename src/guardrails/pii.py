"""Transient PII placeholder restoration for one graph turn."""

import re
from collections.abc import Mapping


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
    ("CARTAO", re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")),
    (
        "CREDENCIAL",
        re.compile(
            r"(?i)\b(?:api[_ -]?key|token|senha|password|secret)"
            r"\s*[:=]\s*\S+"
        ),
    ),
)
_PII_MARKER_PATTERN = re.compile(
    r"\[(?:DADO_SENSIVEL_|PII_)[^\]\r\n]*(?:\]|$)",
    re.IGNORECASE,
)


def extract_pii_markers(text: str) -> set[str]:
    """Return server-style PII markers found verbatim in text."""
    return set(_PII_MARKER_PATTERN.findall(text))


def redact_sensitive_data(
    text: str,
    *,
    namespace: str | None = None,
) -> tuple[str, list[str], dict[str, str]]:
    """Replace sensitive values and return the request-local restoration map."""
    redactions: list[str] = []
    pii_map: dict[str, str] = {}
    sanitized = text

    for kind, pattern in _PII_PATTERNS:
        if pattern.search(sanitized):

            def replace_match(match: re.Match[str]) -> str:
                namespace_part = f"_{namespace}" if namespace else ""
                placeholder = (
                    f"[DADO_SENSIVEL_{kind}{namespace_part}_{len(pii_map) + 1}]"
                )
                pii_map[placeholder] = match.group(0)
                return placeholder

            sanitized = pattern.sub(replace_match, sanitized)
            redactions.append(kind)

    return sanitized, redactions, pii_map


def restore_pii_placeholders(
    content: str,
    pii_map: Mapping[str, str],
) -> str:
    """Restore placeholders in deterministic longest-first order."""
    restored = content
    for placeholder, original in sorted(
        pii_map.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        restored = restored.replace(placeholder, original)
    return restored
