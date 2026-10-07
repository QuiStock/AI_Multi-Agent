from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

Audience = Literal["shared", "employee", "manager"]

VALID_AUDIENCES = frozenset({"shared", "employee", "manager"})
MIN_AUDIENCE_PATH_PARTS = 2


def audience_for_path(documents_root: Path, document_path: Path) -> Audience:
    """Resolve a trusted FAQ audience from the first directory below the root."""
    try:
        relative_path = document_path.resolve().relative_to(documents_root.resolve())
    except ValueError as exc:
        raise ValueError("O documento precisa estar dentro de FAQ_DOCS_DIR.") from exc

    parts = relative_path.parts
    root_audience = documents_root.name.lower()
    if root_audience in VALID_AUDIENCES:
        return cast(Audience, root_audience)

    if len(parts) < MIN_AUDIENCE_PATH_PARTS:
        raise ValueError(
            "Documentos FAQ precisam estar em shared/, employee/ ou manager/."
        )

    audience = parts[0].lower()
    if audience not in VALID_AUDIENCES:
        raise ValueError(
            "Diretório de audiência inválido. Use shared/, employee/ ou manager/."
        )

    return cast(Audience, audience)
