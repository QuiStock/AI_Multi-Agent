from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: int
    email: str
    role_id: int
    store_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class UserAccount:
    user_id: int
    email: str
    role_id: int
    status: str
    store_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    user_id: int
    email: str
