from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from psycopg_pool import ConnectionPool

from src.auth.errors import AccountLookupError
from src.auth.models import UserAccount

_ACCOUNT_LOOKUP = """
SELECT
    ua.id,
    ua.email,
    r.code,
    st.id
FROM "user_account" AS ua
JOIN "role" AS r
  ON r.id = ua.role_id
LEFT JOIN "user_store" AS us
  ON us.user_id = ua.id
 AND us.active IS TRUE
 AND us.unassigned_at IS NULL
LEFT JOIN "store" AS st
  ON st.id = us.store_id
 AND st.status::text = 'ACTIVE'
WHERE ua.email = %s
  AND ua.status::text = 'ACTIVE'
"""


class AccountRepository(Protocol):
    def find_by_email(self, email: str) -> UserAccount | None: ...


class PostgresAccountRepository:
    def __init__(
        self, pool: ConnectionPool, *, statement_timeout_ms: int = 2_000
    ) -> None:
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def find_by_email(self, email: str) -> UserAccount | None:
        try:
            rows = self._fetch_rows(email)
        except AccountLookupError:
            raise
        except Exception as exc:
            raise AccountLookupError from exc
        if not rows:
            return None
        return _account_from_rows(rows)

    def _fetch_rows(self, email: str) -> list[tuple[Any, ...]]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{self._statement_timeout_ms}ms",),
            )
            cursor.execute(_ACCOUNT_LOOKUP, (email,))
            return list(cursor.fetchall())


def _account_from_rows(rows: Sequence[tuple[Any, ...]]) -> UserAccount:
    user_id, email, role_code = _identity(rows)
    return UserAccount(
        user_id=user_id,
        email=email,
        role_code=role_code,
        store_ids=_store_ids(rows),
    )


def _identity(rows: Sequence[tuple[Any, ...]]) -> tuple[int, str, str]:
    user_id = _require_user_id(rows[0][0])
    email = _require_text(rows[0][1])
    role_code = _require_text(rows[0][2])
    for row in rows[1:]:
        if (
            _require_user_id(row[0]) != user_id
            or _require_text(row[1]) != email
            or _require_text(row[2]) != role_code
        ):
            raise AccountLookupError
    return user_id, email, role_code


def _store_ids(rows: Sequence[tuple[Any, ...]]) -> tuple[int, ...]:
    if len(rows) != 1:
        found = tuple(_require_store_id(row[3]) for row in rows if row[3] is not None)
        if len(found) == 1:
            return ()
        return found
    store_id = rows[0][3]
    if store_id is None:
        return ()
    return (_require_store_id(store_id),)


def _require_user_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise AccountLookupError
    return value


def _require_store_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise AccountLookupError
    return value


def _require_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccountLookupError
    return value
