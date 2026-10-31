from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from psycopg_pool import PoolTimeout

from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import AccountLookupError


class Cursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.rows = [] if rows is None else rows
        self.fail = fail
        self.queries: list[str] = []
        self.parameters: list[tuple[Any, ...]] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchall(self) -> list[tuple[Any, ...]]:
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
        yield  # pragma: no cover - this remains a contextmanager generator


def test_account_lookup_reads_role_code_and_the_single_active_store() -> None:
    cursor = Cursor([(7, "person@example.test", "MANAGER", 30)])
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_email("person@example.test")

    assert account is not None
    assert account.user_id == 7
    assert account.email == "person@example.test"
    assert account.role_code == "MANAGER"
    assert account.store_ids == (30,)
    assert cursor.parameters[-1] == ("person@example.test",)
    lookup = cursor.queries[-1]
    assert 'FROM "user_account" AS ua' in lookup
    assert 'JOIN "role" AS r' in lookup
    assert "ON r.id = ua.role_id" in lookup
    assert "us.active IS TRUE" in lookup
    assert "us.unassigned_at IS NULL" in lookup
    assert "st.status::text = 'ACTIVE'" in lookup
    assert "ua.status::text = 'ACTIVE'" in lookup
    assert "WHERE ua.email = %s" in lookup
    assert "region_manager_assignment" not in lookup
    assert "role_id" not in lookup.split("SELECT", 1)[1].split("FROM", 1)[0]


def test_account_lookup_keeps_an_active_account_without_an_active_store() -> None:
    cursor = Cursor([(8, "employee@example.test", "EMPLOYEE", None)])
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_email("employee@example.test")

    assert account is not None
    assert account.role_code == "EMPLOYEE"
    assert account.store_ids == ()


def test_account_lookup_returns_every_active_store_when_scope_is_not_unique() -> None:
    cursor = Cursor(
        [
            (7, "person@example.test", "MANAGER", 30),
            (7, "person@example.test", "MANAGER", 32),
        ]
    )
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_email("person@example.test")

    assert account is not None
    assert account.store_ids == (30, 32)


def test_account_lookup_rejects_an_extra_row_without_an_active_store() -> None:
    cursor = Cursor(
        [
            (7, "person@example.test", "MANAGER", 30),
            (7, "person@example.test", "MANAGER", None),
        ]
    )
    repository = PostgresAccountRepository(Pool(cursor))  # type: ignore[arg-type]

    account = repository.find_by_email("person@example.test")

    assert account is not None
    assert account.store_ids == ()


def test_account_lookup_returns_none_when_account_is_missing() -> None:
    repository = PostgresAccountRepository(Pool(Cursor()))  # type: ignore[arg-type]

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
