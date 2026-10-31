from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    email: str
    role_id: int = 2
    user_id: int | None = None
    role_code: str | None = None
    store_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class UserAccount:
    email: str
    role_id: int
