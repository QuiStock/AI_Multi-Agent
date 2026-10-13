from __future__ import annotations

from typing import Protocol

from psycopg_pool import ConnectionPool

from src.auth.errors import AccountLookupError
from src.auth.models import UserAccount


class AccountRepository(Protocol):
    def find_by_id(self, user_id: int) -> UserAccount | None: ...


class PostgresAccountRepository:
    def __init__(
        self, pool: ConnectionPool, *, statement_timeout_ms: int = 2_000
    ) -> None:
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def find_by_id(self, user_id: int) -> UserAccount | None:
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{self._statement_timeout_ms}ms",),
                )
                cursor.execute(
                    """
                    SELECT ua.id, ua.email, r.code, ua.status::text, st.id
                    FROM user_account AS ua
                    JOIN role AS r ON r.id = ua.role_id
                    LEFT JOIN user_store AS us
                      ON us.user_id = ua.id
                     AND us.active IS TRUE
                     AND us.unassigned_at IS NULL
                    LEFT JOIN store AS st
                      ON st.id = us.store_id
                     AND st.status::text = 'ACTIVE'
                    WHERE ua.id = %s
                    ORDER BY st.id
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
            if not rows:
                return None
            first = rows[0]
            return UserAccount(
                user_id=int(first[0]),
                email=str(first[1]),
                role_code=str(first[2]),
                status=str(first[3]),
                store_ids=tuple(
                    sorted({int(row[4]) for row in rows if row[4] is not None})
                ),
            )
        except Exception as exc:
            raise AccountLookupError from exc
