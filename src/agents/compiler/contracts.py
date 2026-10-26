from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class CompilerResponse(TypedDict):
    status: Literal["success", "blocked"]
    content: str
    citations: list[str]
    error_code: NotRequired[str]
