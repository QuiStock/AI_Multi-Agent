"""Transient PII placeholder restoration for one graph turn."""

from collections.abc import Mapping


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
