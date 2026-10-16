from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from psycopg import errors as psycopg_errors

from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.schemas import ProductCard
from src.agents.product_workflow.tools.product_card_repository import (
    ProductCardRepository,
)
from src.agents.product_workflow.tools.product_card_tool import (
    create_product_card_tool,
)


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None = None):
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self.calls.append((query, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [self.row] if self.row else []


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakePool:
    def __init__(self, cursor: FakeCursor):
        self._connection = FakeConnection(cursor)
        self.calls = 0

    @contextmanager
    def connection(self):
        self.calls += 1
        yield self._connection


def _row() -> tuple[Any, ...]:
    return (
        10,
        20,
        "Leite Integral",
        "Laticínios",
        "SKU-1",
        "PROMOTION",
        5,
        date(2026, 10, 9),
        Decimal("15.00"),
        Decimal("6.50"),
        Decimal("5.52"),
        date(2026, 10, 1),
        date(2026, 10, 10),
    )


@pytest.mark.parametrize("role_code", ["MANAGER", "EMPLOYEE"])
def test_repository_builds_card_with_server_scope_and_fixed_query(
    role_code: str,
) -> None:
    cursor = FakeCursor(_row())
    pool = FakePool(cursor)
    cards = ProductCardRepository(pool).search(
        email="manager@example.test",
        role_code=role_code,
        store_ids=(10,),
        product_query="leite",
    )

    assert len(cards) == 1
    assert cards[0].product_name == "Leite Integral"
    assert cards[0].expiration_date == date(2026, 10, 9)
    sql, params = cursor.calls[1]
    assert "suggestion_log" in sql and "EXPIRED" in sql
    assert "user_store" in sql and "us.active = TRUE" in sql
    assert "JOIN role" not in sql
    assert "ANY(%s::bigint[])" in sql
    assert "available_for_triage = TRUE" in sql
    assert "SENT_TO_MANAGER" in sql
    assert "ILIKE %s" in sql
    assert params == (
        "manager@example.test",
        [10],
        "%leite%",
        "%leite%",
        "%leite%",
        role_code,
        role_code,
    )
    assert cursor.calls[0][0].startswith("SELECT set_config('statement_timeout'")


def test_repository_fails_closed_for_unsupported_role_without_querying() -> None:
    cursor = FakeCursor()
    pool = FakePool(cursor)
    with pytest.raises(PermissionError):
        ProductCardRepository(pool).search(
            email="x@example.test",
            role_code="REGIONAL_MANAGER",
            store_ids=(10,),
            product_query="leite",
        )
    assert pool.calls == 0


def test_repository_rejects_empty_query_before_database_access() -> None:
    pool = FakePool(FakeCursor())
    with pytest.raises(ValueError):
        ProductCardRepository(pool).search(
            email="x@example.test",
            role_code="EMPLOYEE",
            store_ids=(10,),
            product_query=" ",
        )
    assert pool.calls == 0


def test_snapshot_is_evidence_without_database_lookup() -> None:
    class Repository:
        def search(self, **_: Any) -> list[ProductCard]:
            pytest.fail("snapshot question must not look up PostgreSQL")

    class FakeAgent:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "messages": [
                    *state["messages"],
                    AIMessage(content="O card indica leite integral."),
                ]
            }

    executor = ProductWorkflowExecutor(
        repository=Repository(),  # type: ignore[arg-type]
        model=object(),
        agent_factory=lambda **_: FakeAgent(),
    )
    result = executor.invoke(
        {
            "request": {
                "email": "user@example.test",
                "user_id": 42,
                "role_code": "EMPLOYEE",
                "store_ids": [10],
                "request_id": "req-1",
                "product_card": {
                    "product_id": 1427,
                    "suggestion_id": 87531,
                    "product_name": "Café Torrado e Moído 500g",
                    "category_name": "Mercearia",
                    "sku": "CAF-500-TRAD",
                    "suggestion_type": "PROMOTION",
                    "batch_count": 3,
                    "expiration_date": "2026-11-30",
                    "discount_percentage": 15,
                    "reference_sale_price": 29.9,
                    "promotional_price": 25.42,
                    "promotion_valid_from": "2026-10-14",
                    "promotion_valid_until": "2026-10-31",
                },
            },
            "messages": [],
        }
    )
    assert result["answer"] == "O card indica leite integral."
    assert result["evidences"] == [
        {
            "evidence_id": "client-card:1427:87531:CAF-500-TRAD",
            "source_type": "client_card_snapshot",
            "source_id": "CAF-500-TRAD",
            "content": (
                '{"product_id":1427,"suggestion_id":87531,'
                '"product_name":"Café Torrado e Moído 500g",'
                '"category_name":"Mercearia","sku":"CAF-500-TRAD",'
                '"suggestion_type":"PROMOTION","batch_count":3,'
                '"expiration_date":"2026-11-30","discount_percentage":"15",'
                '"reference_sale_price":"29.9","promotional_price":"25.42",'
                '"promotion_valid_from":"2026-10-14",'
                '"promotion_valid_until":"2026-10-31"}'
            ),
            "metadata": {
                "origin": "conversation_request.product_card",
                "product_id": 1427,
                "suggestion_id": 87531,
                "sku": "CAF-500-TRAD",
            },
        }
    ]
    assert "verification_status" not in result["evidences"][0]


def test_executor_denies_unsupported_role_even_with_client_snapshot() -> None:
    def unexpected_agent(**_: Any) -> None:
        pytest.fail("unauthorized role must not start the agent")

    executor = ProductWorkflowExecutor(
        repository=object(),  # type: ignore[arg-type]
        model=object(),
        agent_factory=unexpected_agent,
    )
    result = executor.invoke(
        {
            "request": {
                "email": "user@example.test",
                "user_id": 42,
                "role_code": "REGIONAL_MANAGER",
                "store_ids": [10],
                "request_id": "req-denied",
                "product_card": {"product_name": "Leite Integral", "sku": "SKU-1"},
            },
            "messages": [],
        }
    )
    assert result["error_code"] == "PRODUCT_WORKFLOW_AUTHORIZATION"
    assert result["evidences"] == []


def test_lookup_tool_binds_identity_and_reports_ambiguous_products() -> None:
    class Repository:
        seen: dict[str, Any] | None = None

        def search(self, **kwargs: Any) -> list[ProductCard]:
            self.seen = kwargs
            return [
                ProductCard(
                    product_name="Leite Integral", category_name="Laticínios", sku="1"
                ),
                ProductCard(
                    product_name="Leite Integral", category_name="Laticínios", sku="2"
                ),
            ]

    repository = Repository()
    tool = create_product_card_tool(
        repository=repository,
        email="user@example.test",
        role_code="EMPLOYEE",
        store_ids=(10,),
        request_id="req-2",  # type: ignore[arg-type]
    )
    payload = json.loads(tool.invoke({"product_query": "leite"}))
    assert repository.seen == {
        "email": "user@example.test",
        "role_code": "EMPLOYEE",
        "store_ids": (10,),
        "product_query": "leite",
    }
    assert payload["status"] == "partial"
    assert payload["data"]["outcome"] == "ambiguous"
    assert payload["data"]["cards"] == []
    assert set(payload["data"]["candidates"][0]) == {
        "candidate_ref",
        "product_name",
        "category_name",
        "sku",
    }
    assert len(payload["evidence"]) == 2
    assert all(
        "reference_sale_price" not in item["content"] for item in payload["evidence"]
    )
    assert set(tool.args_schema.model_fields) == {"product_query"}


@pytest.mark.parametrize(
    ("exception", "expected_category"),
    [
        (RuntimeError("connection details must not leak"), "dependency"),
        (psycopg_errors.QueryCanceled("statement timeout"), "timeout"),
    ],
)
def test_lookup_tool_distinguishes_dependency_failures(
    exception: Exception, expected_category: str
) -> None:
    class Repository:
        def search(self, **_: Any) -> list[ProductCard]:
            raise exception

    tool = create_product_card_tool(
        repository=Repository(),  # type: ignore[arg-type]
        email="user@example.test",
        role_code="EMPLOYEE",
        store_ids=(10,),
        request_id="req-3",
    )
    payload = json.loads(tool.invoke({"product_query": "leite"}))
    assert payload["status"] == "error"
    assert payload["error"]["category"] == expected_category
    assert payload["data"] is None
    assert "connection details" not in json.dumps(payload)


def test_lookup_tool_not_found_is_domain_outcome_not_dependency_error() -> None:
    class Repository:
        def search(self, **_: Any) -> list[ProductCard]:
            return []

    tool = create_product_card_tool(
        repository=Repository(),  # type: ignore[arg-type]
        email="user@example.test",
        role_code="EMPLOYEE",
        store_ids=(10,),
        request_id="req-4",
    )
    payload = json.loads(tool.invoke({"product_query": "produto inexistente"}))
    assert payload["status"] == "success"
    assert payload["data"]["outcome"] == "not_found"
    assert payload["error"] is None
    assert payload["evidence"][0]["metadata"]["outcome"] == "not_found"
