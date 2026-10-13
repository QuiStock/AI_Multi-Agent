from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from psycopg_pool import PoolTimeout

from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import AccountLookupError

Row = tuple[int, str, str, str, int | None]


class Cursor:
    def __init__(self, rows: list[Row] | None = None, *, fail: bool = False) -> None:
        self.rows = rows or []
        self.fail = fail
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append((query, parameters))

    def fetchall(self) -> list[Row]:
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self.fake_cursor = cursor

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> Cursor:
        return self.fake_cursor


class Pool:
    def __init__(self, cursor: Cursor) -> None:
        self.fake_cursor = cursor

    @contextmanager
    def connection(self) -> Any:
        yield Connection(self.fake_cursor)


class TimedOutPool:
    @contextmanager
    def connection(self) -> Any:
        raise PoolTimeout("connection checkout timed out")
        yield  # pragma: no cover


def test_lookup_uses_sub_id_and_returns_only_active_store_ids() -> None:
    cursor = Cursor(
        [
            (42, "person@example.test", "MANAGER", "ACTIVE", 9),
            (42, "person@example.test", "MANAGER", "ACTIVE", 4),
            (42, "person@example.test", "MANAGER", "ACTIVE", 9),
        ]
    )
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_id(42)

    assert account is not None
    assert account.user_id == 42
    assert account.email == "person@example.test"
    assert account.role_code == "MANAGER"
    assert account.store_ids == (4, 9)
    query, params = cursor.calls[1]
    assert "WHERE ua.id = %s" in query
    assert "JOIN role AS r ON r.id = ua.role_id" in query
    assert "us.active IS TRUE" in query
    assert "st.status::text = 'ACTIVE'" in query
    assert params == (42,)


def test_lookup_returns_account_without_store_and_none_for_unknown_id() -> None:
    repository = PostgresAccountRepository(
        Pool(Cursor([(42, "person@example.test", "EMPLOYEE", "ACTIVE", None)]))
    )  # type: ignore[arg-type]
    account = repository.find_by_id(42)
    assert account is not None and account.store_ids == ()
    assert PostgresAccountRepository(Pool(Cursor())).find_by_id(99) is None  # type: ignore[arg-type]


def test_lookup_hides_database_errors_and_pool_timeout() -> None:
    for pool in (Pool(Cursor(fail=True)), TimedOutPool()):
        repository = PostgresAccountRepository(pool)  # type: ignore[arg-type]
        with pytest.raises(AccountLookupError) as error:
            repository.find_by_id(42)
        assert str(error.value) == ""
