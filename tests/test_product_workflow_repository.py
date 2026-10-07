from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.agents.product_workflow.models import ProductWorkflowContext
from src.agents.product_workflow.repository import (
    PostgresProductWorkflowRepository,
)


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.queries.append((query, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class FakePool:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor

    def connection(self) -> FakeConnection:
        return FakeConnection(self.cursor_instance)


def test_direct_repository_queries_postgres_with_server_scope_and_no_writes() -> None:
    cursor = FakeCursor(
        [
            (
                10,
                20,
                40,
                "Leite Integral UHT 1L",
                "Laticínios",
                "SKU-40",
                "Loja Centro",
                "ORDER",
                "SENT_TO_MANAGER",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(
        FakePool(cursor),
        statement_timeout_ms=1_500,
    )

    result = repository.search_product_suggestions(
        ProductWorkflowContext(
            email="manager@example.com",
            role_id=2,
            request_id="request-1",
            trace_id="trace-1",
        ),
        "Leite",
    )

    assert [item.suggestion_id for item in result] == [10]
    assert result[0].product_name == "Leite Integral UHT 1L"

    query_text = "\n".join(query for query, _ in cursor.queries).upper()
    assert 'FROM "SUGGESTION"' in query_text
    assert 'JOIN "USER_STORE"' in query_text
    assert "LOWER(UA.EMAIL) = LOWER(%S)" in query_text
    assert "UA.ROLE_ID = %S" in query_text
    assert "INSERT INTO" not in query_text
    assert 'UPDATE "' not in query_text
    assert "DELETE FROM" not in query_text

    commercial_query = cursor.queries[-1]
    assert "manager@example.com" in commercial_query[1]
    assert 2 in commercial_query[1]
    assert 6 in commercial_query[1]


def test_product_search_applies_employee_visibility_and_expired_filter() -> None:
    cursor = FakeCursor(
        [
            (
                11,
                40,
                30,
                "Leite Integral UHT 1L",
                "Laticínios",
                "SKU-40",
                "Loja Centro",
                "ORDER",
                "IN_EMPLOYEE_TRIAGE",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))

    result = repository.search_product_suggestions(
        ProductWorkflowContext(
            email="employee@example.com",
            role_id=3,
            request_id="request-1",
            trace_id="trace-1",
        ),
        "Leite",
    )

    assert result[0].product_name == "Leite Integral UHT 1L"
    query_text = "\n".join(query for query, _ in cursor.queries).upper()
    assert "AVAILABLE_FOR_TRIAGE IS TRUE" in query_text
    assert "STATUS::TEXT = 'IN_EMPLOYEE_TRIAGE'" in query_text
    assert "TYPE::TEXT IN ('ORDER', 'PROMOTION')" in query_text
    assert "EVENT::TEXT = 'EXPIRED'" in query_text
    assert "ILIKE %S ESCAPE" in query_text
    assert "employee@example.com" in cursor.queries[-1][1]


def test_product_search_applies_manager_sent_to_manager_visibility() -> None:
    cursor = FakeCursor(
        [
            (
                12,
                41,
                30,
                "Leite Integral UHT 1L",
                "Laticínios",
                "SKU-41",
                "Loja Centro",
                "PROMOTION",
                "SENT_TO_MANAGER",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))

    result = repository.search_product_suggestions(
        ProductWorkflowContext(
            email="manager@example.com",
            role_id=2,
            request_id="request-2",
            trace_id="trace-2",
        ),
        "Laticínios",
    )

    assert result[0].suggestion_status == "SENT_TO_MANAGER"
    query_text = "\n".join(query for query, _ in cursor.queries).upper()
    assert "STATUS::TEXT = 'SENT_TO_MANAGER'" in query_text
    assert "TYPE::TEXT IN ('ORDER', 'PROMOTION')" in query_text
    assert "AVAILABLE_FOR_TRIAGE IS TRUE" not in query_text


def test_product_detail_projects_triage_without_decision_or_log() -> None:
    cursor = FakeCursor(
        [
            (
                12,
                41,
                30,
                "Leite Integral UHT 1L",
                "Laticínios",
                "SKU-41",
                "Loja Centro",
                "PROMOTION",
                "EMPLOYEE",
                "SENT_TO_MANAGER",
                20,
                25,
                Decimal("10.00"),
                Decimal("15.00"),
                Decimal("6.99"),
                Decimal("5.94"),
                datetime(2026, 6, 8, tzinfo=UTC).date(),
                datetime(2026, 8, 6, tzinfo=UTC).date(),
                datetime(2026, 8, 6, tzinfo=UTC).date(),
                False,
                datetime(2026, 6, 1, tzinfo=UTC),
                datetime(2026, 6, 2, tzinfo=UTC),
                7,
                "Ana Souza",
                "FORWARD",
                datetime(2026, 6, 2, tzinfo=UTC),
                datetime(2026, 6, 2, tzinfo=UTC),
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))

    result = repository.get_product_suggestion_detail(
        ProductWorkflowContext(
            email="manager@example.com",
            role_id=2,
            request_id="request-2",
            trace_id="trace-2",
        ),
        12,
    )

    assert result is not None
    assert result.employee_name == "Ana Souza"
    assert result.last_action == "FORWARD"
    query_text = "\n".join(query for query, _ in cursor.queries).upper()
    assert "SUGGESTION_TRIAGE" in query_text
    assert "SUGGESTION_DECISION" not in query_text
    assert "SUGGESTION_LOG" in query_text
