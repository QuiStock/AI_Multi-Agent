from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from psycopg_pool import PoolTimeout

from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import AccountLookupError


class Cursor:
    def __init__(
        self, row: tuple[str, int] | None = None, *, fail: bool = False
    ) -> None:
        self.row = row
        self.fail = fail
        self.query: str | None = None
        self.parameters: tuple[str, ...] | None = None

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[str, ...]) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.query = query
        self.parameters = parameters

    def fetchone(self) -> tuple[str, int] | None:
        return self.row


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
        yield  # pragma: no cover - this remains a contextmanager generator


def test_account_lookup_is_parameterized_and_reads_only_required_columns() -> None:
    cursor = Cursor(("person@example.test", 2))
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_email("person@example.test")

    assert account is not None
    assert account.email == "person@example.test"
    assert account.role_id == 2
    assert cursor.parameters == ("person@example.test",)
    assert "SELECT email, role_id" in str(cursor.query)
    assert "WHERE email = %s" in str(cursor.query)


def test_account_lookup_returns_none_when_account_is_missing() -> None:
    repository = PostgresAccountRepository(Pool(Cursor(None)))  # type: ignore[arg-type]

    assert repository.find_by_email("missing@example.test") is None


def test_account_lookup_hides_operational_database_errors() -> None:
    repository = PostgresAccountRepository(Pool(Cursor(fail=True)))  # type: ignore[arg-type]

    with pytest.raises(AccountLookupError) as error:
        repository.find_by_email("person@example.test")

    assert str(error.value) == ""


def test_account_lookup_translates_pool_timeout() -> None:
    repository = PostgresAccountRepository(TimedOutPool())  # type: ignore[arg-type]

    with pytest.raises(AccountLookupError):
        repository.find_by_email("person@example.test")
