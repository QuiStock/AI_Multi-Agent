from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from src.agents.product_workflow.contracts import ProductWorkflowContext
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
                "Leite Integral UHT 1L",
                None,
                "SKU-40",
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
            user_id=7,
            role_code="MANAGER",
            store_ids=(30,),
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
    assert "UA.ID = %S" in query_text
    assert "S.STORE_ID = ANY(%S)" in query_text
    assert "INSERT INTO" not in query_text
    assert 'UPDATE "' not in query_text
    assert "DELETE FROM" not in query_text

    commercial_query = cursor.queries[-1]
    assert "manager@example.com" in commercial_query[1]
    assert 7 in commercial_query[1]
    assert [30] in commercial_query[1]
    assert commercial_query[1][-2:] == (7, 0)
    assert (
        "ORDER BY P.NAME ASC, P.SKU ASC, S.STORE_ID ASC, S.ID ASC"
        in commercial_query[0].upper()
    )


def test_product_search_applies_employee_visibility_and_expired_filter() -> None:
    cursor = FakeCursor(
        [
            (
                11,
                40,
                "Leite Integral UHT 1L",
                None,
                "SKU-40",
                "ORDER",
                "IN_EMPLOYEE_TRIAGE",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))

    result = repository.search_product_suggestions(
        ProductWorkflowContext(
            email="employee@example.com",
            user_id=8,
            role_code="EMPLOYEE",
            store_ids=(30,),
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
                "Leite Integral UHT 1L",
                "Laticínios",
                "SKU-41",
                "PROMOTION",
                "SENT_TO_MANAGER",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))

    result = repository.search_product_suggestions(
        ProductWorkflowContext(
            email="manager@example.com",
            user_id=7,
            role_code="MANAGER",
            store_ids=(30,),
            request_id="request-2",
            trace_id="trace-2",
        ),
        "Leite",
    )

    assert result[0].suggestion_status == "SENT_TO_MANAGER"
    query_text = "\n".join(query for query, _ in cursor.queries).upper()
    assert "STATUS::TEXT = 'SENT_TO_MANAGER'" in query_text
    assert "TYPE::TEXT IN ('ORDER', 'PROMOTION')" in query_text
    assert "AVAILABLE_FOR_TRIAGE IS TRUE" not in query_text


def test_product_search_matches_only_product_name_and_sku() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-3",
        trace_id="trace-3",
    )

    repository.search_product_suggestions(context, "1427")

    query, params = next(
        (query, params)
        for query, params in cursor.queries
        if "TRANSLATE(P.NAME" in query.upper()
    )
    assert "TRANSLATE(P.NAME, %S, %S) ILIKE %S" in query.upper()
    assert "TRANSLATE(P.SKU, %S, %S) ILIKE %S" in query.upper()
    assert "P.ID = %S" not in query.upper()
    assert "S.ID = %S" not in query.upper()
    assert "%1427%" in params


def test_product_search_folds_accents_in_the_pattern() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-4",
        trace_id="trace-4",
    )

    repository.search_product_suggestions(context, "chá gelado")

    params = next(
        params
        for query, params in cursor.queries
        if "TRANSLATE(P.NAME" in query.upper()
    )
    assert "%cha gelado%" in params


def test_product_search_uses_stable_order_and_page_offset() -> None:
    cursor = FakeCursor(
        [
            (
                12,
                41,
                "Leite Integral UHT 1L",
                None,
                "SKU-41",
                "PROMOTION",
                "SENT_TO_MANAGER",
            )
        ]
    )
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-page-2",
        trace_id="trace-page-2",
    )

    result = repository.search_product_suggestions(context, "Leite", page=2)

    assert [item.suggestion_id for item in result] == [12]
    query, params = cursor.queries[-1]
    assert "ORDER BY P.NAME ASC, P.SKU ASC, S.STORE_ID ASC, S.ID ASC" in query.upper()
    assert "LIMIT %S" in query.upper()
    assert "OFFSET %S" in query.upper()
    assert params[-2:] == (7, 6)


def test_product_search_rejects_page_outside_the_supported_range() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-invalid-page",
        trace_id="trace-invalid-page",
    )

    try:
        repository.search_product_suggestions(context, "Leite", page=101)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid page should be rejected")
    assert cursor.queries == []


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
            user_id=7,
            role_code="MANAGER",
            store_ids=(30,),
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


def test_list_and_expiration_use_page_offset_without_a_keyset() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-list-page",
        trace_id="trace-list-page",
    )

    assert repository.list_product_suggestions(context, "ORDER", page=2) == []
    assert (
        repository.find_promotions_by_expiration(
            context,
            "nearest",
            reference_date=date(2026, 10, 3),
            page=2,
        )
        == []
    )
    assert (
        repository.find_promotions_by_expiration(
            context,
            reference_date=date(2026, 10, 3),
            until=date(2026, 10, 31),
            page=2,
        )
        == []
    )

    list_query, list_params = cursor.queries[1]
    extreme_query, extreme_params = cursor.queries[3]
    until_query, until_params = cursor.queries[5]
    assert _sql(list_query, "ORDER BY P.NAME ASC, P.SKU ASC, S.STORE_ID ASC, S.ID ASC")
    assert _sql(
        extreme_query,
        "ORDER BY V.PRODUCT_NAME ASC, V.SKU ASC, V.STORE_ID ASC, V.ID ASC",
    )
    assert _sql(
        until_query,
        "ORDER BY S.PROMOTION_VALID_UNTIL ASC, P.NAME ASC, P.SKU ASC, "
        "S.STORE_ID ASC, S.ID ASC",
    )
    assert list_params[-2:] == (7, 6)
    assert extreme_params[-2:] == (7, 6)
    assert until_params[-2:] == (7, 6)
    for query, _params in (cursor.queries[1], cursor.queries[3], cursor.queries[5]):
        assert "OFFSET %S" in query.upper()
        assert "> (%S" not in query.upper()


def test_list_filters_both_types_with_any_and_stable_order() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-both-types",
        trace_id="trace-both-types",
    )

    assert (
        repository.list_product_suggestions(
            context,
            ["PROMOTION", "ORDER"],
            page=1,
        )
        == []
    )

    query, params = cursor.queries[-1]
    assert "S.TYPE::TEXT = ANY(%S)" in query.upper()
    assert "ORDER BY P.NAME ASC, P.SKU ASC, S.STORE_ID ASC, S.ID ASC" in " ".join(
        query.upper().split()
    )
    assert params[-3] == ["ORDER", "PROMOTION"]
    assert params[-2:] == (7, 0)

    try:
        repository.list_product_suggestions(context, ["ORDER", "ORDER"], page=1)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicated suggestion type should be rejected")
    assert len(cursor.queries) == 2


def test_list_and_expiration_reject_page_outside_the_supported_range() -> None:
    cursor = FakeCursor([])
    repository = PostgresProductWorkflowRepository(FakePool(cursor))
    context = ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-invalid-list-page",
        trace_id="trace-invalid-list-page",
    )

    for call in (
        lambda: repository.list_product_suggestions(context, "PROMOTION", page=101),
        lambda: repository.find_promotions_by_expiration(context, "longest", page=0),
    ):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("Invalid page should be rejected")

    assert cursor.queries == []


def _sql(query: str, fragment: str) -> bool:
    return fragment in " ".join(query.upper().split())
