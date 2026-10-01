from __future__ import annotations

from typing import Protocol

from psycopg_pool import ConnectionPool

from src.auth.errors import AccountLookupError
from src.auth.models import UserAccount


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
            with self._pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (f"{self._statement_timeout_ms}ms",),
                    )
                    cursor.execute(
                        "SELECT email, role_id FROM user_account "
                        "WHERE email = %s LIMIT 1",
                        (email,),
                    )
                    row = cursor.fetchone()
            if row is None:
                return None
            return UserAccount(email=str(row[0]), role_id=int(row[1]))
        except Exception as exc:
            raise AccountLookupError from exc
