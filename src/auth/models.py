from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    email: str
    role_id: int


@dataclass(frozen=True, slots=True)
class UserAccount:
    email: str
    role_id: int
