from __future__ import annotations

from psycopg_pool import ConnectionPool


def create_postgres_pool(
    *, dsn: str, timeout_seconds: float, open_immediately: bool = False
) -> ConnectionPool:
    return ConnectionPool(
        conninfo=dsn,
        kwargs={"connect_timeout": max(1, int(timeout_seconds))},
        min_size=1,
        max_size=8,
        timeout=timeout_seconds,
        open=open_immediately,
    )
