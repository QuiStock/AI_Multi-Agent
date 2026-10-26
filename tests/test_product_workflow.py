import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.product_workflow.contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.filters import PRODUCT_SEARCH_PAGE_SIZE
from src.agents.product_workflow.product_workflow_node import run_product_workflow_node
from src.agents.product_workflow.repository import ProductWorkflowDependencyError
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
    product_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=suggestion_id,
        store_id=store_id,
        product_id=product_id,
        status=status,
        available_for_triage=available_for_triage,
        type=suggestion_type,
        updated_at=updated_at or NOW,
        product_name=product_name,
    )


def search_record(
    suggestion_id: int = 1,
    *,
    product_id: int = 10,
    product_name: str = "Leite Integral UHT 1L",
    suggestion_status: str = "IN_EMPLOYEE_TRIAGE",
) -> ProductSuggestionSearchRecord:
    return ProductSuggestionSearchRecord(
        suggestion_id=suggestion_id,
        product_id=product_id,
        product_name=product_name,
        category_name="Laticínios",
        sku=f"SKU-{product_id}",
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
        suggestion_type="ORDER",
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
        self.search_queries: list[str] = []
        self.search_pages: list[int] = []
        self.detail_ids: list[int] = []
        self.missing_detail_ids: set[int] = set()

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        page: int = 1,
    ) -> list[ProductSuggestionSearchRecord]:
        self.contexts.append(context)
        self.search_queries.append(product_query)
        self.search_pages.append(page)
        status = (
            "SENT_TO_MANAGER"
            if context.role_code == "MANAGER"
            else "IN_EMPLOYEE_TRIAGE"
        )
        start = (page - 1) * PRODUCT_SEARCH_PAGE_SIZE
        return [
            search_record(
                record.id,
                product_id=record.product_id,
                product_name=record.product_name or "Leite Integral UHT 1L",
                suggestion_status=status,
            )
            for record in self.records[start : start + PRODUCT_SEARCH_PAGE_SIZE + 1]
        ]

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        self.contexts.append(context)
        self.detail_ids.append(suggestion_id)
        if suggestion_id in self.missing_detail_ids:
            return None
        role = "manager" if context.role_code == "MANAGER" else "employee"
        return detail_record(suggestion_id, role=role)


def context() -> ProductWorkflowContext:
    return ProductWorkflowContext(
        email="manager@example.com",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id="request-1",
        trace_id="trace-1",
    )


def employee_context() -> ProductWorkflowContext:
    return ProductWorkflowContext(
        email="employee@example.com",
        user_id=8,
        role_code="EMPLOYEE",
        store_ids=(30,),
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
        "list_suggestions",
        "get_promotion_by_expiration",
    ]
    payload = tools[0].invoke({"product_query": "Leite"})

    assert repository.contexts == [context(), context()]
    decoded = json.loads(payload)
    assert decoded["status"] == "success"
    assert decoded["data"]["status"] == "unique"
    assert "candidates" not in decoded["data"]
    assert "outcome" not in decoded["data"]
    assert decoded["data"]["page"] == 1
    assert decoded["data"]["has_more"] is False
    assert decoded["data"]["suggestion"]["current_batch_count"] == 25
    assert "suggestion_id" not in decoded["data"]["suggestion"]
    assert decoded["evidence"][0]["source_type"] == "product_workflow"
    assert "Leite Integral UHT 1L" in decoded["evidence"][0]["content"]


def test_detail_projects_manager_triage_without_decision_or_log() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=context(),
    )

    detail_payload = json.loads(tools[1].invoke({"selection_id": "candidate-1"}))

    assert detail_payload["status"] == "success"
    assert detail_payload["data"]["status"] == "unique"
    assert detail_payload["data"]["visibility"] == "manager"
    assert "triage" not in detail_payload["data"]
    assert "origin" not in detail_payload["data"]["card"]
    assert detail_payload["data"]["card"]["current_batch_count"] == 25


def test_detail_projects_employee_card_without_manager_triage() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    detail_payload = json.loads(tools[1].invoke({"selection_id": "candidate-1"}))

    assert detail_payload["data"]["visibility"] == "employee"
    assert "triage" not in detail_payload["data"]


def test_detail_rejects_tampered_selection_reference() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[1].invoke({"selection_id": "not-an-id"}))

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_SELECTION_REF"
    assert payload["data"] is None


def test_product_search_returns_partial_numbered_candidates() -> None:
    repository = FakeRepository(
        [
            suggestion(1, product_name="Arroz Branco"),
            suggestion(2, product_id=11, product_name="Arroz Integral"),
        ]
    )
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "Leite"}))

    assert payload["status"] == "success"
    assert payload["data"]["status"] == "ambiguous"
    assert "outcome" not in payload["data"]
    assert [item["position"] for item in payload["data"]["candidates"]] == [1, 2]
    assert len(payload["evidence"]) == 1
    assert "response" not in payload
    assert "warnings" not in payload


def test_product_search_pages_six_suggestions_with_stable_global_numbering() -> None:
    repository = FakeRepository(
        [suggestion(item, product_name=f"Produto {item}") for item in range(1, 14)]
    )
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    first_page = json.loads(tools[0].invoke({"product_query": "Produto", "page": 1}))
    second_page = json.loads(tools[0].invoke({"product_query": "Produto", "page": 2}))

    assert first_page["data"]["status"] == "ambiguous"
    assert first_page["data"]["has_more"] is True
    assert [item["position"] for item in first_page["data"]["candidates"]] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert len(first_page["evidence"]) == 1
    assert second_page["data"]["status"] == "ambiguous"
    assert second_page["data"]["has_more"] is True
    assert [item["position"] for item in second_page["data"]["candidates"]] == [
        7,
        8,
        9,
        10,
        11,
        12,
    ]
    assert len(second_page["evidence"]) == 1
    assert repository.search_pages == [1, 2]


def test_last_single_item_page_stays_ambiguous_without_loading_details() -> None:
    repository = FakeRepository(
        [suggestion(item, product_name=f"Produto {item}") for item in range(1, 8)]
    )
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "Produto", "page": 2}))

    assert payload["data"]["status"] == "ambiguous"
    assert payload["data"]["has_more"] is False
    assert [item["position"] for item in payload["data"]["candidates"]] == [7]
    assert len(payload["evidence"]) == 1
    assert repository.detail_ids == []


def test_product_search_not_found_is_not_reported_as_unavailable() -> None:
    repository = FakeRepository([])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "inexistente"}))

    assert payload["status"] == "success"
    assert payload["data"]["status"] == "not_found"
    assert "outcome" not in payload["data"]
    assert len(payload["evidence"]) == 1
    assert "warnings" not in payload


def test_product_search_unique_race_is_reclassified_as_not_found() -> None:
    repository = FakeRepository([suggestion(1)])
    repository.missing_detail_ids.add(1)
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "SKU-10"}))

    assert payload["data"]["status"] == "not_found"
    assert "suggestion" not in payload["data"]


def test_product_search_accepts_partial_name_and_sku() -> None:
    repository = FakeRepository([suggestion(1)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    for reference in ("Leite", "Integral UHT", "SKU-10"):
        payload = json.loads(tools[0].invoke({"product_query": reference}))
        assert payload["data"]["status"] == "unique"

    assert repository.search_queries == ["Leite", "Integral UHT", "SKU-10"]


def test_product_search_dependency_failure_is_unavailable() -> None:
    class UnavailableRepository(FakeRepository):
        def search_product_suggestions(
            self,
            context: ProductWorkflowContext,
            product_query: str,
            *,
            page: int = 1,
        ) -> list[ProductSuggestionSearchRecord]:
            raise ProductWorkflowDependencyError("database timeout")

    tools = build_product_workflow_tools(
        repository=UnavailableRepository([]),
        context=employee_context(),
    )

    payload = json.loads(tools[0].invoke({"product_query": "Leite"}))

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "PRODUCT_WORKFLOW_UNAVAILABLE"
    assert payload["data"] is None
    assert "Tente novamente mais tarde" in payload["error"]["message"]


def test_selection_is_revalidated_after_role_or_expiration_changes() -> None:
    repository = FakeRepository([suggestion(1)])
    repository.missing_detail_ids.add(1)
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )

    payload = json.loads(tools[1].invoke({"selection_id": "candidate-1"}))

    assert payload["status"] == "error"
    assert payload["error"]["category"] == "not_found"
    assert payload["data"] is None


def test_selection_is_rejected_when_candidate_identity_changes() -> None:
    class ChangedCandidateRepository(FakeRepository):
        def get_product_suggestion_detail(
            self,
            context: ProductWorkflowContext,
            suggestion_id: int,
        ) -> ProductSuggestionDetailRecord | None:
            detail = super().get_product_suggestion_detail(context, suggestion_id)
            return detail.model_copy(update={"sku": "SKU-CHANGED"}) if detail else None

    repository = ChangedCandidateRepository([suggestion(1), suggestion(2)])
    tools = build_product_workflow_tools(
        repository=repository,
        context=employee_context(),
    )
    search_payload = json.loads(tools[0].invoke({"product_query": "Leite"}))
    selection_id = search_payload["data"]["candidates"][0]["selection_id"]

    detail_payload = json.loads(tools[1].invoke({"selection_id": selection_id}))

    assert detail_payload["status"] == "error"
    assert detail_payload["error"]["category"] == "not_found"


def _request() -> dict[str, Any]:
    return {
        "email": "employee@example.com",
        "user_id": 7,
        "role_code": "EMPLOYEE",
        "store_ids": [30],
        "request_id": "request-1",
        "trace_id": "trace-1",
    }


def _tool_message(payload: dict[str, Any]) -> ToolMessage:
    return ToolMessage(
        name="get_suggestion_for_product",
        tool_call_id="tool-call-1",
        content=json.dumps(payload),
    )


def _ambiguous_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "data": {
            "product_query": "Arroz",
            "page": 1,
            "has_more": False,
            "status": "ambiguous",
            "candidates": [
                {
                    "position": 1,
                    "selection_id": "candidate-1-aaaaaaaaaaaaaaaa",
                    "product_name": "Arroz Branco",
                    "sku": "SKU-10",
                    "suggestion_type": "ORDER",
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": "product-search:1",
                "source_type": "product_workflow",
                "source_id": "product-search:1",
                "content": '{"product_name":"Arroz Branco"}',
                "metadata": {},
            }
        ],
        "error": None,
        "meta": {
            "tool_name": "get_suggestion_for_product",
            "tool_version": "1.0.0",
            "tool_call_id": "request-1:get_suggestion_for_product",
            "trace_id": "trace-1",
            "timestamp": "2026-10-03T12:00:00Z",
        },
    }


def _detail_payload() -> dict[str, Any]:
    content = (
        '{"status":"unique","visibility":"manager","card":'
        '{"product_name":"Arroz Branco"}}'
    )
    return {
        "schema_version": "1.0",
        "status": "success",
        "data": {
            "status": "unique",
            "visibility": "manager",
            "card": {
                "selection_id": "candidate-1-aaaaaaaaaaaaaaaa",
                "product_name": "Arroz Branco",
                "sku": "SKU-10",
                "suggestion_type": "ORDER",
            },
        },
        "evidence": [
            {
                "evidence_id": "suggestion-detail:1",
                "source_type": "product_workflow",
                "source_id": "suggestion-detail:1",
                "content": content,
                "metadata": {},
            }
        ],
        "error": None,
        "meta": {
            "tool_name": "get_suggestion_detail",
            "tool_version": "1.0.0",
            "tool_call_id": "request-1:get_suggestion_detail",
            "trace_id": "trace-1",
            "timestamp": "2026-10-03T12:00:00Z",
        },
    }


def test_unknown_tool_name_stays_an_error_and_is_not_renamed() -> None:
    missing_name = ProductWorkflowExecutor._tool_called({"status": "success"})
    foreign_name = ProductWorkflowExecutor._tool_called(
        {
            **_ambiguous_payload(),
            "meta": {
                **_ambiguous_payload()["meta"],
                "tool_name": "product_card_lookup",
            },
        }
    )
    known_name = ProductWorkflowExecutor._tool_called(_ambiguous_payload())

    assert missing_name["status"] == "error"
    assert missing_name["tool_name"] == "unknown"
    assert (
        ProductWorkflowExecutor._tool_error_code([missing_name])
        == "PRODUCT_WORKFLOW_INVALID_RESULT"
    )
    assert foreign_name["status"] == "error"
    assert foreign_name["tool_name"] == "product_card_lookup"
    assert known_name["status"] == "success"
    assert known_name["tool_name"] == "get_suggestion_for_product"


def test_executor_reads_text_blocks_and_drops_the_serialized_body() -> None:
    blocks = ProductWorkflowExecutor._answer(
        [AIMessage(content=[{"type": "text", "text": "Encontrei o chá."}])]
    )
    dumped = ProductWorkflowExecutor._answer(
        [AIMessage(content="[{'type': 'text', 'text': 'Não achei.'}]")]
    )

    assert blocks == "Encontrei o chá."
    assert dumped == ""
    assert "annotations" not in blocks


def test_executor_returns_the_model_answer_and_called_tools() -> None:
    class FakeAgent:
        def invoke(self, state: dict[str, Any], **_: Any) -> dict[str, Any]:
            return {
                "messages": [
                    *state["messages"],
                    _tool_message(_ambiguous_payload()),
                    AIMessage(content="Encontrei mais de uma sugestão."),
                ]
            }

    result = ProductWorkflowExecutor(
        repository=FakeRepository([]),
        model="fake-model",
        agent_factory=lambda **_: FakeAgent(),
    ).invoke(
        messages=[HumanMessage(content="Busque arroz")],
        request_context=_request(),
    )

    assert result["status"] == "success"
    assert result["answer"] == "Encontrei mais de uma sugestão."
    assert result["tools_called"][0]["tool_name"] == "get_suggestion_for_product"
    assert "error_code" not in result


def test_node_numbers_an_ambiguous_page_and_keeps_evidence() -> None:
    class FakeExecutor:
        def invoke(
            self, *, messages: list[Any], request_context: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "status": "success",
                "answer": "Texto do modelo.",
                "tools_called": [
                    {
                        "tool_name": "get_suggestion_for_product",
                        "status": "success",
                        "toolResult": _ambiguous_payload(),
                    }
                ],
            }

    result = run_product_workflow_node(
        {
            "request": _request(),
            "messages": [HumanMessage(content="Busque arroz")],
        },
        executor=FakeExecutor(),  # type: ignore[arg-type]
    )

    workflow = result["agent_results"]["product_workflow"]
    assert workflow["lookup_status"] == "ambiguous"
    assert workflow["status"] == "success"
    assert workflow["answer"] == (
        "1. Arroz Branco\nEscolha o número da opção que você quer consultar."
    )
    assert result["evidences"][0]["evidence_id"] == "product-search:1"
    assert "errors" not in result


def test_node_keeps_only_the_successful_detail_evidence() -> None:
    class FakeExecutor:
        def invoke(
            self, *, messages: list[Any], request_context: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "status": "success",
                "answer": "O leite tem 25 unidades no lote atual.",
                "tools_called": [
                    {
                        "tool_name": "get_suggestion_for_product",
                        "status": "success",
                        "toolResult": _ambiguous_payload(),
                    },
                    {
                        "tool_name": "get_suggestion_detail",
                        "status": "success",
                        "toolResult": _detail_payload(),
                    },
                ],
            }

    result = run_product_workflow_node(
        {
            "request": _request(),
            "messages": [HumanMessage(content="3")],
        },
        executor=FakeExecutor(),  # type: ignore[arg-type]
    )

    workflow = result["agent_results"]["product_workflow"]
    assert workflow["lookup_status"] == "unique"
    assert workflow["status"] == "success"
    assert workflow["evidence_ids"] == ["suggestion-detail:1"]
    assert [item["evidence_id"] for item in result["evidences"]] == [
        "suggestion-detail:1"
    ]
    assert '"status":"unique"' in result["evidences"][0]["content"]


def test_node_keeps_not_found_when_the_model_fails_after_the_tool() -> None:
    def factory(**kwargs: Any) -> Any:
        tool = kwargs["tools"][0]

        class FakeAgent:
            def invoke(self, state: dict[str, Any], **_: Any) -> dict[str, Any]:
                tool.invoke({"product_query": "Arroz"})
                raise RuntimeError("model failed after the tool")

        return FakeAgent()

    executor = ProductWorkflowExecutor(
        repository=FakeRepository([]),
        model="fake-model",
        agent_factory=factory,
    )
    result = run_product_workflow_node(
        {
            "request": _request(),
            "messages": [HumanMessage(content="Busque arroz")],
        },
        executor=executor,
    )

    workflow = result["agent_results"]["product_workflow"]
    assert workflow["status"] == "success"
    assert workflow["lookup_status"] == "not_found"
    assert workflow["answer"] == "Não há sugestões válidas para essa busca."
    assert "error_code" not in workflow


def test_executor_denies_unsupported_role_before_the_model() -> None:
    def unexpected_agent(**_: Any) -> None:
        raise AssertionError("unauthorized role must not start the agent")

    result = ProductWorkflowExecutor(
        repository=FakeRepository([]),
        model="fake-model",
        agent_factory=unexpected_agent,
    ).invoke(
        messages=[HumanMessage(content="Busque arroz")],
        request_context={**_request(), "role_code": "REGIONAL_MANAGER"},
    )

    assert result["status"] == "error"
    assert result["error_code"] == "PRODUCT_WORKFLOW_AUTHORIZATION"


def listing_record(
    suggestion_id: int,
    *,
    product_name: str | None = None,
    sku: str | None = None,
    suggestion_type: str = "ORDER",
) -> ProductSuggestionListingRecord:
    return ProductSuggestionListingRecord(
        suggestion_id=suggestion_id,
        product_id=10,
        store_id=20,
        product_name=product_name or "Leite Integral UHT 1L",
        category_name="Laticínios",
        sku=sku or "SKU-10",
        store_name="Loja Centro",
        suggestion_type=suggestion_type,
        suggestion_status="SENT_TO_MANAGER",
        promotion_valid_until=date(2026, 10, 20),
    )


class ListingRepository:
    def __init__(self, records: list[ProductSuggestionListingRecord]) -> None:
        self.records = records
        self.pages: list[int] = []
        self.detail_ids: list[int] = []

    def list_product_suggestions(
        self,
        context: ProductWorkflowContext,
        suggestion_type: str | list[str],
        *,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        selected = (
            {suggestion_type}
            if isinstance(suggestion_type, str)
            else set(suggestion_type)
        )
        matched = [
            record for record in self.records if record.suggestion_type in selected
        ]
        self.pages.append(page)
        start = (page - 1) * PRODUCT_SEARCH_PAGE_SIZE
        return matched[start : start + PRODUCT_SEARCH_PAGE_SIZE + 1]

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: str | None = None,
        *,
        reference_date: date | None = None,
        until: date | None = None,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        self.pages.append(page)
        start = (page - 1) * PRODUCT_SEARCH_PAGE_SIZE
        return self.records[start : start + PRODUCT_SEARCH_PAGE_SIZE + 1]

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        self.detail_ids.append(suggestion_id)
        return detail_record(suggestion_id, role="manager")


def test_list_pages_six_suggestions_and_omits_cursor() -> None:
    records = [
        listing_record(index, product_name=f"Item {index}", sku=f"SKU-{index}")
        for index in range(1, 8)
    ]
    repository = ListingRepository(records)
    tools = build_product_workflow_tools(repository=repository, context=context())

    first_page = json.loads(tools[2].invoke({"suggestion_type": "ORDER", "page": 1}))
    second_page = json.loads(tools[2].invoke({"suggestion_type": "ORDER", "page": 2}))

    assert first_page["data"]["status"] == "ambiguous"
    assert first_page["data"]["page"] == 1
    assert first_page["data"]["has_more"] is True
    assert [item["position"] for item in first_page["data"]["candidates"]] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert "cursor" not in first_page["data"]
    assert second_page["data"]["status"] == "ambiguous"
    assert second_page["data"]["page"] == 2
    assert second_page["data"]["has_more"] is False
    assert [item["position"] for item in second_page["data"]["candidates"]] == [7]
    assert "cursor" not in second_page["data"]
    assert repository.detail_ids == []
    assert repository.pages == [1, 2]


def test_list_page_one_with_a_single_item_is_unique() -> None:
    repository = ListingRepository([listing_record(1)])
    tools = build_product_workflow_tools(repository=repository, context=context())

    payload = json.loads(tools[2].invoke({"suggestion_type": "ORDER"}))

    assert payload["data"]["status"] == "unique"
    assert payload["data"]["page"] == 1
    assert payload["data"]["has_more"] is False
    assert "cursor" not in payload["data"]
    assert repository.detail_ids == [1]


def test_expiration_pages_six_promotions_and_omits_cursor() -> None:
    records = [
        listing_record(
            index,
            product_name=f"Promo {index}",
            sku=f"SKU-{index}",
            suggestion_type="PROMOTION",
        )
        for index in range(1, 8)
    ]
    repository = ListingRepository(records)
    tools = build_product_workflow_tools(repository=repository, context=context())

    first_page = json.loads(tools[3].invoke({"direction": "nearest", "page": 1}))
    second_page = json.loads(tools[3].invoke({"direction": "nearest", "page": 2}))

    assert first_page["data"]["status"] == "ambiguous"
    assert first_page["data"]["page"] == 1
    assert first_page["data"]["has_more"] is True
    assert "cursor" not in first_page["data"]
    assert second_page["data"]["status"] == "ambiguous"
    assert second_page["data"]["page"] == 2
    assert second_page["data"]["has_more"] is False
    assert [item["position"] for item in second_page["data"]["candidates"]] == [7]
    assert "cursor" not in second_page["data"]
    assert repository.detail_ids == []


def test_node_numbers_list_and_expiration_pages_without_a_cursor() -> None:
    records = [
        listing_record(index, product_name=f"Item {index}", sku=f"SKU-{index}")
        for index in range(1, 8)
    ]
    repository = ListingRepository(records)
    tools = build_product_workflow_tools(repository=repository, context=context())
    listed = json.loads(tools[2].invoke({"suggestion_type": "ORDER", "page": 1}))
    expired = json.loads(tools[3].invoke({"direction": "longest", "page": 1}))
    exhausted = json.loads(tools[2].invoke({"suggestion_type": "PROMOTION", "page": 3}))

    listed_answer = _answer_from_tool("list_suggestions", listed)
    expired_answer = _answer_from_tool("get_promotion_by_expiration", expired)
    exhausted_answer = _answer_from_tool("list_suggestions", exhausted, answer="")

    assert listed_answer == (
        "Os pedidos vigentes são:\n"
        "1. Item 1\n"
        "2. Item 2\n"
        "3. Item 3\n"
        "4. Item 4\n"
        "5. Item 5\n"
        "6. Item 6\n"
        "Para ver a próxima página, peça a página 2."
    )
    assert "cursor" not in listed_answer
    assert expired_answer.endswith("Para ver a próxima página, peça a página 2.")
    assert "cursor" not in expired_answer
    assert exhausted["data"]["status"] == "not_found"
    assert exhausted["data"]["page"] == 3
    assert "cursor" not in exhausted["data"]
    assert exhausted_answer == "Não há mais sugestões válidas nesta busca."


def test_node_continues_numbering_on_the_second_page() -> None:
    records = [
        listing_record(index, product_name=f"Item {index}", sku=f"SKU-{index}")
        for index in range(1, 14)
    ]
    repository = ListingRepository(records)
    tools = build_product_workflow_tools(repository=repository, context=context())
    second_page = json.loads(tools[2].invoke({"suggestion_type": "ORDER", "page": 2}))

    answer = _answer_from_tool("list_suggestions", second_page)

    assert answer.startswith("Os pedidos vigentes são:\n7. Item 7\n")
    assert "12. Item 12\n" in answer
    assert answer.endswith("Para ver a próxima página, peça a página 3.")


def _answer_from_tool(
    tool_name: str,
    payload: dict[str, Any],
    *,
    answer: str = "Texto do modelo.",
) -> str:
    class FakeExecutor:
        def invoke(
            self, *, messages: list[Any], request_context: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "status": "success",
                "answer": answer,
                "tools_called": [
                    {
                        "tool_name": tool_name,
                        "status": "success",
                        "toolResult": payload,
                    }
                ],
            }

    result = run_product_workflow_node(
        {
            "request": _request(),
            "messages": [HumanMessage(content="Liste as sugestões")],
        },
        executor=FakeExecutor(),  # type: ignore[arg-type]
    )
    return str(result["agent_results"]["product_workflow"]["answer"])


def test_list_accepts_both_types_and_labels_each_candidate() -> None:
    records = [
        listing_record(
            1, product_name="Chá Gelado", sku="SKU-1", suggestion_type="ORDER"
        ),
        listing_record(
            2,
            product_name="Leite Integral",
            sku="SKU-2",
            suggestion_type="PROMOTION",
        ),
    ]
    repository = ListingRepository(records)
    tools = build_product_workflow_tools(repository=repository, context=context())

    payload = json.loads(
        tools[2].invoke({"suggestion_type": ["PROMOTION", "ORDER"], "page": 1})
    )
    answer = _answer_from_tool("list_suggestions", payload)

    assert payload["data"]["status"] == "ambiguous"
    assert payload["data"]["suggestion_types"] == ["ORDER", "PROMOTION"]
    assert payload["data"]["page"] == 1
    assert payload["data"]["has_more"] is False
    assert "suggestion_type" not in payload["data"]
    assert [item["suggestion_type"] for item in payload["data"]["candidates"]] == [
        "ORDER",
        "PROMOTION",
    ]
    assert answer == (
        "As sugestões vigentes são:\n"
        "1. Chá Gelado (pedido)\n"
        "2. Leite Integral (promoção)\n"
        "Escolha o número da opção que você quer consultar."
    )
    assert repository.detail_ids == []


def test_single_type_list_keeps_the_name_and_the_type_not_found_sentence() -> None:
    repository = ListingRepository(
        [
            listing_record(1, product_name="Chá Gelado", sku="SKU-1"),
            listing_record(2, product_name="Arroz Branco", sku="SKU-2"),
        ]
    )
    tools = build_product_workflow_tools(repository=repository, context=context())

    listed = json.loads(tools[2].invoke({"suggestion_type": ["ORDER"], "page": 1}))
    missing_type = json.loads(tools[2].invoke({"suggestion_type": "PROMOTION"}))

    assert listed["data"]["status"] == "ambiguous"
    assert listed["data"]["suggestion_types"] == ["ORDER"]
    assert _answer_from_tool("list_suggestions", listed) == (
        "Os pedidos vigentes são:\n"
        "1. Chá Gelado\n"
        "2. Arroz Branco\n"
        "Escolha o número da opção que você quer consultar."
    )
    assert (
        _answer_from_tool("list_suggestions", missing_type, answer="")
        == "Não há sugestões válidas desse tipo."
    )


def test_mixed_list_not_found_uses_the_broader_sentence() -> None:
    repository = ListingRepository([])
    tools = build_product_workflow_tools(repository=repository, context=context())

    payload = json.loads(
        tools[2].invoke({"suggestion_type": ["ORDER", "PROMOTION"], "page": 1})
    )
    duplicate = json.loads(tools[2].invoke({"suggestion_type": ["ORDER", "ORDER"]}))

    assert payload["data"]["status"] == "not_found"
    assert payload["data"]["suggestion_types"] == ["ORDER", "PROMOTION"]
    assert (
        _answer_from_tool("list_suggestions", payload, answer="")
        == "Não há sugestões válidas."
    )
    assert duplicate["status"] == "error"
