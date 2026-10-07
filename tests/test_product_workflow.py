import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.models import (
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)
from src.agents.product_workflow.tools.tools import build_product_workflow_tools

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def suggestion(
    suggestion_id: int,
    *,
    product_id: int = 10,
    store_id: int = 20,
    status: str = "GENERATED",
    available_for_triage: bool = True,
    updated_at: datetime | None = None,
    suggestion_type: str = "ORDER",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=suggestion_id,
        store_id=store_id,
        product_id=product_id,
        status=status,
        available_for_triage=available_for_triage,
        type=suggestion_type,
        updated_at=updated_at or NOW,
    )


def search_record(
    suggestion_id: int = 1,
    *,
    product_id: int = 10,
    store_id: int = 20,
    product_name: str = "Leite Integral UHT 1L",
    suggestion_status: str = "IN_EMPLOYEE_TRIAGE",
) -> ProductSuggestionSearchRecord:
    return ProductSuggestionSearchRecord(
        suggestion_id=suggestion_id,
        product_id=product_id,
        store_id=store_id,
        product_name=product_name,
        category_name="Laticínios",
        sku=f"SKU-{product_id}",
        store_name="Loja Centro",
        suggestion_type="ORDER",
        suggestion_status=suggestion_status,
    )


def detail_record(
    suggestion_id: int = 1,
    *,
    role: str = "employee",
) -> ProductSuggestionDetailRecord:
    return ProductSuggestionDetailRecord(
        suggestion_id=suggestion_id,
        product_id=10,
        store_id=20,
        product_name="Leite Integral UHT 1L",
        category_name="Laticínios",
        sku="SKU-10",
        store_name="Loja Centro",
        suggestion_type="PROMOTION",
        origin="EMPLOYEE",
        status="SENT_TO_MANAGER" if role == "manager" else "IN_EMPLOYEE_TRIAGE",
        ml_batch_count=20,
        current_batch_count=25,
        ml_discount_percentage=10,
        current_discount_percentage=15,
        reference_sale_price=6.99,
        promotional_price=5.94,
        promotion_valid_from=datetime(2026, 6, 8).date(),
        promotion_valid_until=datetime(2026, 8, 6).date(),
        physical_expiration_date=datetime(2026, 8, 6).date(),
        available_for_triage=role == "employee",
        created_at=NOW,
        updated_at=NOW,
        employee_id=42 if role == "manager" else None,
        employee_name="Ana Souza" if role == "manager" else None,
        last_action="FORWARD" if role == "manager" else None,
        forwarded_at=NOW if role == "manager" else None,
        triage_updated_at=NOW if role == "manager" else None,
    )


class FakeRepository:
    def __init__(self, records: list[SimpleNamespace]) -> None:
        self.records = records
        self.contexts: list[ProductWorkflowContext] = []

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        limit: int = 6,
    ) -> list[ProductSuggestionSearchRecord]:
        self.contexts.append(context)
        status = "SENT_TO_MANAGER" if context.role_id == 2 else "IN_EMPLOYEE_TRIAGE"
        return [
            search_record(record.id, suggestion_status=status)
            for record in self.records[:limit]
        ]

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        self.contexts.append(context)
        role = "manager" if context.role_id == 2 else "employee"
        return detail_record(suggestion_id, role=role)


def context() -> ProductWorkflowContext:
    return ProductWorkflowContext(
        email="manager@example.com",
        role_id=2,
        request_id="request-1",
        trace_id="trace-1",
    )


def employee_context() -> ProductWorkflowContext:
    return ProductWorkflowContext(
        email="employee@example.com",
        role_id=3,
        request_id="request-2",
        trace_id="trace-2",
    )


def test_tool_applies_authorized_context_and_returns_original_evidence() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=context(),
    )

    assert [item.name for item in tools] == [
        "get_suggestion_for_product",
        "get_suggestion_detail",
    ]
    payload = tools[0].invoke({"product_query": "Leite"})

    assert repository.contexts == [context()]
    decoded = json.loads(payload)
    assert decoded["status"] == "success"
    assert decoded["data"]["outcome"] == "found"
    assert decoded["data"]["candidates"][0]["position"] == 1
    assert decoded["data"]["candidates"][0]["selection_ref"] == "1"
    assert decoded["evidence"][0]["evidence_id"] == "product-search:suggestion:1"
    assert decoded["evidence"][0]["source_id"] == "postgresql:suggestion:1"


def test_detail_projects_manager_triage_without_decision_or_log() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=context(),
    )

    search_payload = json.loads(tools[0].invoke({"product_query": "Leite"}))
    detail_payload = json.loads(
        tools[1].invoke(
            {"selection_ref": search_payload["data"]["candidates"][0]["selection_ref"]}
        )
    )

    assert detail_payload["status"] == "success"
    assert detail_payload["data"]["visibility"] == "manager"
    assert detail_payload["data"]["triage"]["last_action"] == "FORWARD"
    assert "decision" not in detail_payload["data"]
    assert "logs" not in detail_payload["data"]


def test_detail_projects_employee_card_without_manager_triage() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    search_payload = json.loads(tools[0].invoke({"product_query": "Leite"}))
    detail_payload = json.loads(
        tools[1].invoke(
            {"selection_ref": search_payload["data"]["candidates"][0]["selection_ref"]}
        )
    )

    assert detail_payload["data"]["visibility"] == "employee"
    assert detail_payload["data"]["triage"] is None


def test_detail_rejects_tampered_selection_reference() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[1].invoke({"selection_ref": "not-an-id"}))

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_SELECTION_REF"
    assert payload["data"] is None


def test_product_search_returns_partial_numbered_candidates() -> None:
    repository = FakeRepository([suggestion(1), suggestion(2, product_id=11)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "Leite"}))

    assert payload["status"] == "partial"
    assert payload["data"]["outcome"] == "ambiguous"
    assert [item["position"] for item in payload["data"]["candidates"]] == [1, 2]
    assert payload["warnings"][0]["code"] == "MULTIPLE_MATCHES"


def test_executor_projects_tool_evidence_to_graph_shape(monkeypatch) -> None:
    repository = FakeRepository([suggestion(1)])
    evidence_message = ToolMessage(
        name="get_suggestion_for_product",
        tool_call_id="tool-call-1",
        content=(
            '{"evidence":[{"evidence_id":"e-1",'
            '"source_type":"product_workflow","source_id":"s-1",'
            '"content":"Fonte original.","metadata":{"store_id":"20"}}]}'
        ),
    )

    class FakeAgent:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "messages": [
                    HumanMessage(content="Quais sugestões estão ativas?"),
                    evidence_message,
                    AIMessage(content="Há uma sugestão ativa."),
                ]
            }

    captured: dict[str, Any] = {}

    def fake_factory(**kwargs: Any) -> FakeAgent:
        captured.update(kwargs)
        return FakeAgent()

    executor = ProductWorkflowExecutor(
        repository=repository,
        model="fake-model",
        agent_factory=fake_factory,
    )
    result = executor.invoke(
        {
            "request": {
                "email": "employee@example.com",
                "role_id": 2,
                "request_id": "request-1",
                "trace_id": "trace-1",
            },
            "messages": [HumanMessage(content="Quais sugestões estão ativas?")],
        }
    )

    assert captured["card"].id == "product_workflow"
    assert result["answer"] == "Há uma sugestão ativa."
    assert result["evidences"] == [
        {
            "evidence_id": "e-1",
            "source_type": "product_workflow",
            "source_id": "s-1",
            "content": "Fonte original.",
            "metadata": {"store_id": "20"},
        }
    ]
