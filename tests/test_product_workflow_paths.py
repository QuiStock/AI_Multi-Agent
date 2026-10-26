"""Every Product Workflow path through the real executor, tools and graph."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agents.judge.jev_node import (
    JEV_UNAVAILABLE_RESPONSE,
    JUDGE_BLOCKED_RESPONSE,
)
from src.agents.product_workflow.contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)
from src.agents.product_workflow.executor import ProductWorkflowExecutor
from src.agents.product_workflow.filters import PRODUCT_SEARCH_PAGE_SIZE
from src.agents.product_workflow.product_workflow_node import (
    run_product_workflow_node,
)
from src.agents.product_workflow.repository import ProductWorkflowDependencyError
from src.api.dependencies import (
    get_authenticated_principal,
    get_graph,
    get_trace_repository,
)
from src.auth.models import AuthenticatedPrincipal
from src.graphs.agent_graph import create_agent_graph
from src.graphs.state import GraphState
from src.main import create_app

SENT_AT = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
STORE_ID = 810000504
UNAVAILABLE = (
    "Desculpe, não foi possível consultar essas informações agora. "
    "Tente novamente mais tarde."
)
CHOOSE = "Escolha o número da opção que você quer consultar."
NOT_FOUND_DEFAULT = (
    "Não encontrei uma sugestão autorizada para esse produto. "
    "Você pode informar o SKU ou verificar o nome do produto?"
)

CATALOG: list[tuple[str, str, str, date | None]] = [
    ("Agua de Coco Fluxo 1L", "PWF-FLOW-007", "PROMOTION", date(2026, 10, 24)),
    ("Arroz Tipo 1 Fluxo 5kg", "PWF-FLOW-001", "ORDER", None),
    ("Biscoito Fluxo 200g", "PWF-FLOW-008", "PROMOTION", date(2026, 10, 26)),
    ("Cafe Torrado Fluxo 500g", "PWF-FLOW-002", "ORDER", None),
    ("Chá Gelado de Limão 1,5L", "F1-SKU-018", "ORDER", None),
    ("Feijao Carioca Fluxo 1kg", "PWF-FLOW-003", "ORDER", None),
    ("Iogurte Fluxo 170g", "PWF-FLOW-009", "PROMOTION", date(2026, 10, 27)),
    ("Leite Integral 1L", "F1-SKU-014", "PROMOTION", date(2026, 10, 28)),
    ("Macarrao Parafuso Fluxo 500g", "PWF-FLOW-004", "ORDER", None),
    ("Nectar Fluxo 1L", "PWF-FLOW-010", "PROMOTION", date(2026, 10, 30)),
    ("Oleo de Soja Fluxo 900ml", "PWF-FLOW-005", "ORDER", None),
    ("Queijo Minas Fluxo 200g", "PWF-FLOW-011", "PROMOTION", date(2026, 11, 6)),
    ("Suco de Laranja Fluxo 1L", "PWF-FLOW-006", "ORDER", None),
    ("Vinho Fluxo 1L", "PWF-FLOW-012", "PROMOTION", date(2026, 12, 2)),
]


def _detail(index: int) -> ProductSuggestionDetailRecord:
    name, sku, kind, valid_until = CATALOG[index]
    is_order = kind == "ORDER"
    return ProductSuggestionDetailRecord(
        suggestion_id=100 + index,
        product_id=500 + index,
        store_id=STORE_ID,
        product_name=name,
        category_name="Fluxo Quistock",
        sku=sku,
        store_name="Loja Demo 04",
        suggestion_type=kind,
        origin="ML",
        status="SENT_TO_MANAGER",
        ml_batch_count=12 if is_order else None,
        current_batch_count=9 if is_order else None,
        reference_sale_price=None if is_order else 15.9,
        promotional_price=None if is_order else 12.67,
        promotion_valid_from=None if is_order else date(2026, 10, 23),
        promotion_valid_until=valid_until,
        available_for_triage=False,
        created_at=SENT_AT,
        updated_at=SENT_AT,
    )


def _listing(detail: ProductSuggestionDetailRecord) -> ProductSuggestionListingRecord:
    return ProductSuggestionListingRecord(
        suggestion_id=detail.suggestion_id,
        product_id=detail.product_id,
        store_id=detail.store_id,
        product_name=detail.product_name,
        category_name=detail.category_name,
        sku=detail.sku,
        store_name=detail.store_name,
        suggestion_type=detail.suggestion_type,
        suggestion_status=detail.status,
        promotion_valid_until=detail.promotion_valid_until,
    )


def _search(detail: ProductSuggestionDetailRecord) -> ProductSuggestionSearchRecord:
    return ProductSuggestionSearchRecord(
        suggestion_id=detail.suggestion_id,
        product_id=detail.product_id,
        product_name=detail.product_name,
        category_name=detail.category_name,
        sku=detail.sku,
        suggestion_type=detail.suggestion_type,
        suggestion_status=detail.status,
    )


def _page(rows: Sequence[Any], page: int) -> list[Any]:
    start = (page - 1) * PRODUCT_SEARCH_PAGE_SIZE
    return list(rows[start : start + PRODUCT_SEARCH_PAGE_SIZE + 1])


class Demo04Repository:
    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.details = [_detail(index) for index in range(len(CATALOG))]
        self.fail_with = fail_with
        self.detail_fail_with: Exception | None = None
        self.hidden_ids: set[int] = set()
        self.contexts: list[ProductWorkflowContext] = []

    def _check(self, context: ProductWorkflowContext) -> None:
        self.contexts.append(context)
        if self.fail_with is not None:
            raise self.fail_with

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        page: int = 1,
    ) -> list[ProductSuggestionSearchRecord]:
        self._check(context)
        query = product_query.strip().lower()
        if not query:
            raise ValueError("Consulta de produto inválida")
        matched = [
            _search(item)
            for item in self.details
            if query in item.product_name.lower() or query in item.sku.lower()
        ]
        return _page(matched, page)

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        self.contexts.append(context)
        if self.detail_fail_with is not None:
            raise self.detail_fail_with
        if suggestion_id in self.hidden_ids:
            return None
        return next(
            (item for item in self.details if item.suggestion_id == suggestion_id),
            None,
        )

    def list_product_suggestions(
        self,
        context: ProductWorkflowContext,
        suggestion_type: str | Sequence[str],
        *,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        self._check(context)
        selected = (
            {suggestion_type}
            if isinstance(suggestion_type, str)
            else set(suggestion_type)
        )
        matched = [
            _listing(item) for item in self.details if item.suggestion_type in selected
        ]
        return _page(matched, page)

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: str | None = None,
        *,
        reference_date: date | None = None,
        until: date | None = None,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        self._check(context)
        floor = reference_date or SENT_AT.date()
        promotions = [
            item
            for item in self.details
            if item.suggestion_type == "PROMOTION"
            and item.promotion_valid_until is not None
            and item.promotion_valid_until >= floor
        ]
        if until is not None:
            matched = sorted(
                (item for item in promotions if item.promotion_valid_until <= until),  # type: ignore[operator]
                key=lambda item: (item.promotion_valid_until, item.product_name),
            )
        else:
            if direction not in {"nearest", "longest"}:
                raise ValueError("Direção de validade inválida")
            dates = [item.promotion_valid_until for item in promotions]
            extreme = min(dates) if direction == "nearest" else max(dates)  # type: ignore[type-var]
            matched = [
                item for item in promotions if item.promotion_valid_until == extreme
            ]
        return _page([_listing(item) for item in matched], page)


Step = Callable[[list[dict[str, Any]]], tuple[str, dict[str, Any]]]


def call(name: str, **arguments: Any) -> Step:
    return lambda _: (name, arguments)


def pick(position: int) -> Step:
    def step(results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        candidates = results[-1]["data"]["candidates"]
        chosen = next(item for item in candidates if item["position"] == position)
        return "get_suggestion_detail", {"selection_id": chosen["selection_id"]}

    return step


class ScriptedAgent:
    def __init__(self, tools: Sequence[Any], steps: Sequence[Step], answer: str):
        self.tools = {tool.name: tool for tool in tools}
        self.steps = steps
        self.answer = answer
        self.fail_after_tools = False

    def invoke(self, state: dict[str, Any], **_: Any) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for step in self.steps:
            name, arguments = step(results)
            results.append(json.loads(self.tools[name].invoke(arguments)))
        if self.fail_after_tools:
            raise RuntimeError("model failed after the tools")
        return {"messages": [*state["messages"], AIMessage(content=self.answer)]}


def executor(
    repository: Demo04Repository,
    steps: Sequence[Step],
    *,
    answer: str = "",
    fail_after_tools: bool = False,
) -> ProductWorkflowExecutor:
    def factory(*, card: Any, model: Any, tools: Sequence[Any]) -> ScriptedAgent:
        agent = ScriptedAgent(tools, steps, answer)
        agent.fail_after_tools = fail_after_tools
        return agent

    return ProductWorkflowExecutor(
        repository=repository,  # type: ignore[arg-type]
        model="fake-model",
        agent_factory=factory,
    )


class ProductRouter:
    def invoke(
        self, _: list[AnyMessage], *, request_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"route": "product_workflow", "reason": "Consulta", "status": "success"}


class RecordingCompiler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        evidences = kwargs.get("evidences") or []
        names = [
            json.loads(item["content"]).get("card", {}).get("product_name")
            or json.loads(item["content"]).get("suggestion", {}).get("product_name")
            or item.get("source_id")
            for item in evidences
        ]
        return {
            "content": "Card: " + ", ".join(str(name) for name in names),
            "citations": [item["evidence_id"] for item in evidences],
            "status": "success",
        }


class ScriptedJudge:
    def __init__(self, *results: dict[str, Any]) -> None:
        self.results = list(results) or [{"status": "approved"}]
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self,
        *,
        user_question: str | None,
        response_draft: dict[str, Any] | None,
        evidences: list[dict[str, Any]],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"evidences": evidences, "question": user_question})
        result = self.results[min(len(self.calls), len(self.results)) - 1]
        return {"reason": "Controlado.", "evidence_count": len(evidences), **result}


def _passed_input(_: GraphState) -> GraphState:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "OK",
            "redactions": [],
        }
    }


def _passing_output(state: GraphState) -> GraphState:
    result: GraphState = {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "violations": [],
        }
    }
    if state.get("final_response"):
        result["final_response"] = state["final_response"]
    return result


class EmptyContext:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        return []


def build_graph(
    product_executor: ProductWorkflowExecutor,
    *,
    compiler: RecordingCompiler | None = None,
    judge: ScriptedJudge | None = None,
    checkpointer: MemorySaver | None = None,
) -> Any:
    return create_agent_graph(
        input_guardrail=_passed_input,
        router=ProductRouter(),
        capabilities={
            "product_workflow": partial(
                run_product_workflow_node, executor=product_executor
            )
        },
        judge=judge or ScriptedJudge(),
        compiler=compiler or RecordingCompiler(),
        output_guardrail=_passing_output,
        context_enricher=EmptyContext(),
        checkpointer=checkpointer,
    )


def _request(request_id: str = "req-1", **overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "request_id": request_id,
        "trace_id": request_id,
        "email": "manager@example.test",
        "user_id": 7,
        "role_code": "MANAGER",
        "store_ids": [STORE_ID],
        "conversation_id": "conv-1",
        "sent_at": SENT_AT,
    }
    request.update(overrides)
    return request


def run(
    graph: Any,
    message: str,
    *,
    request_id: str = "req-1",
    thread_id: str | None = None,
    **request: Any,
) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    return graph.invoke(
        {
            "request": _request(request_id, **request),
            "messages": [HumanMessage(content=message, id=f"{request_id}:user")],
        },
        config=config,
    )


def numbered(names: Sequence[str], start: int, footer: str) -> str:
    lines = [f"{start + index}. {name}" for index, name in enumerate(names)]
    return "\n".join([*lines, footer])


FLUXO = [name for name, *_ in CATALOG if "fluxo" in name.lower()]
ORDERS = [name for name, _, kind, _ in CATALOG if kind == "ORDER"]
PROMOTIONS = [name for name, _, kind, _ in CATALOG if kind == "PROMOTION"]


def _final(result: dict[str, Any]) -> tuple[str, str]:
    final = result["final_response"]
    return final["status"], final["content"]


# get_suggestion_for_product


def test_search_unique_goes_through_compiler_and_judge() -> None:
    compiler = RecordingCompiler()
    judge = ScriptedJudge()
    graph = build_graph(
        executor(
            Demo04Repository(),
            [call("get_suggestion_for_product", product_query="Arroz Tipo 1")],
        ),
        compiler=compiler,
        judge=judge,
    )

    status, content = _final(run(graph, "Qual a sugestão do Arroz Tipo 1 Fluxo?"))

    assert (status, content) == ("success", "Card: Arroz Tipo 1 Fluxo 5kg")
    assert len(compiler.calls) == 1
    assert [
        item["evidence_id"].split(":")[0] for item in judge.calls[0]["evidences"]
    ] == ["product-search"]


def test_search_ambiguous_pages_use_fixed_text_and_continue_numbering() -> None:
    repository = Demo04Repository()
    compiler = RecordingCompiler()
    judge = ScriptedJudge()

    first = run(
        build_graph(
            executor(
                repository, [call("get_suggestion_for_product", product_query="fluxo")]
            ),
            compiler=compiler,
            judge=judge,
        ),
        "Busque o produto Fluxo",
    )
    second = run(
        build_graph(
            executor(
                repository,
                [call("get_suggestion_for_product", product_query="fluxo", page=2)],
            ),
            compiler=compiler,
            judge=judge,
        ),
        "Quero a página 2",
    )
    third = run(
        build_graph(
            executor(
                repository,
                [call("get_suggestion_for_product", product_query="fluxo", page=3)],
            ),
            compiler=compiler,
            judge=judge,
        ),
        "Quero a página 3",
    )

    assert _final(first) == (
        "clarification_required",
        numbered(FLUXO[:6], 1, "Para ver a próxima página, peça a página 2."),
    )
    assert _final(second) == (
        "clarification_required",
        numbered(FLUXO[6:12], 7, CHOOSE),
    )
    assert _final(third) == (
        "clarification_required",
        "Não há mais sugestões válidas nesta busca.",
    )
    assert compiler.calls == []
    assert len(judge.calls) == 3


def test_ambiguous_rejection_does_not_return_to_the_compiler() -> None:
    compiler = RecordingCompiler()
    judge = ScriptedJudge(
        {
            "status": "insufficient_evidence",
            "reason_code": "unsupported_claim",
            "error_code": "JUDGE_REJECTED",
        }
    )

    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_suggestion_for_product", product_query="fluxo")],
            ),
            compiler=compiler,
            judge=judge,
        ),
        "Busque o produto Fluxo",
    )

    assert compiler.calls == []
    assert len(judge.calls) == 1
    assert _final(result) == ("clarification_required", JUDGE_BLOCKED_RESPONSE)


def test_search_not_found_uses_the_query_sentence_only_without_model_text() -> None:
    silent = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_suggestion_for_product", product_query="chocolate")],
            )
        ),
        "Tem sugestão de chocolate?",
    )
    spoken = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_suggestion_for_product", product_query="chocolate")],
                answer="Não achei chocolate.",
            )
        ),
        "Tem sugestão de chocolate?",
    )

    assert _final(silent) == (
        "clarification_required",
        "Não há sugestões válidas para essa busca.",
    )
    assert _final(spoken) == (
        "clarification_required",
        "Não há sugestões válidas para essa busca.",
    )


# get_suggestion_detail


@pytest.mark.parametrize(
    ("first_step", "position", "expected"),
    [
        (call("get_suggestion_for_product", product_query="fluxo"), 2, FLUXO[1]),
        (
            call("get_suggestion_for_product", product_query="fluxo", page=2),
            7,
            FLUXO[6],
        ),
        (call("list_suggestions", suggestion_type="ORDER"), 3, ORDERS[2]),
        (call("get_promotion_by_expiration", until="2026-10-27"), 2, PROMOTIONS[1]),
    ],
)
def test_detail_publishes_only_its_evidence(
    first_step: Step, position: int, expected: str
) -> None:
    compiler = RecordingCompiler()
    judge = ScriptedJudge()
    graph = build_graph(
        executor(Demo04Repository(), [first_step, pick(position)]),
        compiler=compiler,
        judge=judge,
    )

    result = run(graph, str(position))

    assert _final(result) == ("success", f"Card: {expected}")
    evidences = judge.calls[0]["evidences"]
    assert len(evidences) == 1
    assert evidences[0]["evidence_id"].startswith("suggestion-detail:")
    assert '"status":"unique"' in evidences[0]["content"]
    assert result["agent_results"]["product_workflow"]["lookup_status"] == "unique"
    assert "Loja Demo" not in evidences[0]["content"]
    assert "reference_sale_price" not in evidences[0]["content"]


def test_detail_with_a_tampered_selection_is_not_found() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [
                    call(
                        "get_suggestion_detail",
                        selection_id="candidate-101-0000000000000000",
                    )
                ],
            )
        ),
        "2",
    )

    assert _final(result) == ("clarification_required", NOT_FOUND_DEFAULT)
    assert result["agent_results"]["product_workflow"]["lookup_status"] == "not_found"


def test_detail_with_a_malformed_selection_is_not_found() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_suggestion_detail", selection_id="candidate-x")],
            )
        ),
        "2",
    )

    assert _final(result) == ("clarification_required", NOT_FOUND_DEFAULT)


def test_detail_outside_the_scope_is_not_found() -> None:
    repository = Demo04Repository()
    repository.hidden_ids = {101}

    result = run(
        build_graph(
            executor(
                repository,
                [call("get_suggestion_for_product", product_query="fluxo"), pick(2)],
            )
        ),
        "2",
    )

    assert _final(result) == ("clarification_required", NOT_FOUND_DEFAULT)


def test_detail_dependency_failure_is_unavailable() -> None:
    repository = Demo04Repository()
    compiler = RecordingCompiler()

    def failing_detail(results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        repository.detail_fail_with = ProductWorkflowDependencyError("timeout")
        return pick(2)(results)

    result = run(
        build_graph(
            executor(
                repository,
                [
                    call("get_suggestion_for_product", product_query="fluxo"),
                    failing_detail,
                ],
            ),
            compiler=compiler,
        ),
        "2",
    )

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["errors"][-1]["code"] == "PRODUCT_WORKFLOW_UNAVAILABLE"
    assert result["errors"][-1]["retryable"] is True
    assert compiler.calls == []


# list_suggestions


@pytest.mark.parametrize(
    ("suggestion_type", "names", "labels"),
    [
        ("ORDER", ORDERS, False),
        ("PROMOTION", PROMOTIONS, False),
        (["ORDER", "PROMOTION"], [name for name, *_ in CATALOG], True),
    ],
)
def test_list_pages_with_continuous_numbering(
    suggestion_type: Any, names: list[str], labels: bool
) -> None:
    kinds = {name: kind for name, _, kind, _ in CATALOG}

    def label(name: str) -> str:
        if not labels:
            return name
        return f"{name} (pedido)" if kinds[name] == "ORDER" else f"{name} (promoção)"

    kinds_requested = (
        {suggestion_type} if isinstance(suggestion_type, str) else set(suggestion_type)
    )
    if kinds_requested == {"ORDER"}:
        heading = "Os pedidos vigentes são:"
    elif kinds_requested == {"PROMOTION"}:
        heading = "As promoções vigentes são:"
    else:
        heading = "As sugestões vigentes são:"

    pages = []
    for page in (1, 2):
        result = run(
            build_graph(
                executor(
                    Demo04Repository(),
                    [
                        call(
                            "list_suggestions",
                            suggestion_type=suggestion_type,
                            page=page,
                        )
                    ],
                )
            ),
            f"página {page}",
        )
        pages.append(_final(result))

    assert pages[0] == (
        "clarification_required",
        heading
        + "\n"
        + numbered(
            [label(name) for name in names[:6]],
            1,
            "Para ver a próxima página, peça a página 2.",
        ),
    )
    footer = (
        CHOOSE if len(names) <= 12 else "Para ver a próxima página, peça a página 3."
    )
    assert pages[1] == (
        "clarification_required",
        heading + "\n" + numbered([label(name) for name in names[6:12]], 7, footer),
    )


def test_list_page_beyond_the_end_is_not_found() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("list_suggestions", suggestion_type="ORDER", page=3)],
            )
        ),
        "página 3",
    )

    assert _final(result) == (
        "clarification_required",
        "Não há mais sugestões válidas nesta busca.",
    )


# get_promotion_by_expiration


@pytest.mark.parametrize(
    ("direction", "expected"),
    [("nearest", "Agua de Coco Fluxo 1L"), ("longest", "Vinho Fluxo 1L")],
)
def test_expiration_extreme_is_unique(direction: str, expected: str) -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_promotion_by_expiration", direction=direction)],
            )
        ),
        "Qual promoção vence primeiro?",
    )

    assert _final(result) == ("success", f"Card: {expected}")


def test_expiration_until_lists_by_validity() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_promotion_by_expiration", until="2026-10-27")],
            )
        ),
        "Quais promoções vencem até 27/10/2026?",
    )

    assert _final(result) == (
        "clarification_required",
        numbered(PROMOTIONS[:3], 1, CHOOSE),
    )


def test_expiration_until_before_the_message_date_is_not_found() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_promotion_by_expiration", until="2026-10-22")],
            )
        ),
        "Quais promoções vencem até 22/10/2026?",
    )

    assert _final(result) == (
        "clarification_required",
        "Não há promoções válidas nesse período.",
    )


# Errors shared by the four tools

ALL_FIRST_CALLS = [
    call("get_suggestion_for_product", product_query="fluxo"),
    call("list_suggestions", suggestion_type="ORDER"),
    call("get_promotion_by_expiration", direction="nearest"),
]


@pytest.mark.parametrize("step", ALL_FIRST_CALLS)
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProductWorkflowDependencyError("db down"), "PRODUCT_WORKFLOW_UNAVAILABLE"),
        (PermissionError("role"), "PRODUCT_WORKFLOW_FORBIDDEN"),
        (RuntimeError("boom"), "PRODUCT_WORKFLOW_INTERNAL"),
    ],
)
def test_repository_failures_are_controlled_unavailable(
    step: Step, error: Exception, code: str
) -> None:
    compiler = RecordingCompiler()
    result = run(
        build_graph(
            executor(Demo04Repository(fail_with=error), [step]), compiler=compiler
        ),
        "consulta",
    )

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["errors"][-1]["code"] == code
    assert compiler.calls == []
    assert "db down" not in json.dumps(result["agent_results"], default=str)


@pytest.mark.parametrize(
    "step",
    [
        call("get_suggestion_for_product", product_query="fluxo", page=0),
        call("get_suggestion_for_product", product_query="fluxo", page=101),
        call("get_suggestion_for_product", product_query="   "),
        call("list_suggestions", suggestion_type="ORDER", page=0),
        call("list_suggestions", suggestion_type="MONITOR"),
        call("get_promotion_by_expiration", until="amanhã"),
        call("get_promotion_by_expiration", direction="nearest", page=101),
    ],
)
def test_invalid_tool_arguments_end_in_the_controlled_error(step: Step) -> None:
    compiler = RecordingCompiler()
    result = run(
        build_graph(executor(Demo04Repository(), [step]), compiler=compiler),
        "consulta",
    )

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["agent_results"]["product_workflow"]["status"] in {
        "error",
        "unavailable",
    }
    assert compiler.calls == []


# Executor and node


def test_model_that_skips_the_tools_is_unavailable() -> None:
    result = run(
        build_graph(executor(Demo04Repository(), [], answer="Sem consulta.")),
        "Busque arroz",
    )

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["errors"][-1]["code"] == "PRODUCT_WORKFLOW_TOOL_NOT_CALLED"


def test_model_failure_after_the_tool_keeps_the_tool_outcome() -> None:
    result = run(
        build_graph(
            executor(
                Demo04Repository(),
                [call("get_suggestion_for_product", product_query="fluxo")],
                fail_after_tools=True,
            )
        ),
        "Busque o produto Fluxo",
    )

    assert _final(result) == (
        "clarification_required",
        numbered(FLUXO[:6], 1, "Para ver a próxima página, peça a página 2."),
    )


@pytest.mark.parametrize(
    "request_override",
    [
        {"role_code": "REGIONAL_MANAGER"},
        {"store_ids": []},
        {"user_id": None},
    ],
)
def test_missing_identity_is_denied_before_the_model(
    request_override: dict[str, Any],
) -> None:
    def unexpected(**_: Any) -> Any:
        raise AssertionError("the model must not start")

    product_executor = ProductWorkflowExecutor(
        repository=Demo04Repository(),  # type: ignore[arg-type]
        model="fake-model",
        agent_factory=unexpected,
    )
    result = run(build_graph(product_executor), "Busque arroz", **request_override)

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["errors"][-1]["code"] == "PRODUCT_WORKFLOW_AUTHORIZATION"


def test_client_card_skips_the_tools_and_uses_the_snapshot_evidence() -> None:
    judge = ScriptedJudge()

    def no_tools(*, card: Any, model: Any, tools: Sequence[Any]) -> ScriptedAgent:
        assert tools == []
        return ScriptedAgent(tools, [], "Explicação do card.")

    product_executor = ProductWorkflowExecutor(
        repository=Demo04Repository(),  # type: ignore[arg-type]
        model="fake-model",
        agent_factory=no_tools,
    )
    result = run(
        build_graph(product_executor, judge=judge),
        "Explique esse card",
        product_card={"product_name": "Arroz Tipo 1 Fluxo 5kg", "sku": "PWF-FLOW-001"},
    )

    assert result["final_response"]["status"] == "success"
    assert [item["source_type"] for item in judge.calls[0]["evidences"]] == [
        "client_card_snapshot"
    ]


def test_invalid_client_card_is_controlled() -> None:
    def unexpected(**_: Any) -> Any:
        raise AssertionError("the model must not start")

    product_executor = ProductWorkflowExecutor(
        repository=Demo04Repository(),  # type: ignore[arg-type]
        model="fake-model",
        agent_factory=unexpected,
    )
    result = run(
        build_graph(product_executor),
        "Explique esse card",
        product_card={"product_name": ""},
    )

    assert _final(result) == ("error", UNAVAILABLE)
    assert result["errors"][-1]["code"] == "PRODUCT_WORKFLOW_INVALID_SNAPSHOT"


# Judge outcomes after a successful detail

DETAIL_STEPS = [call("get_suggestion_for_product", product_query="fluxo"), pick(2)]


def test_correctable_rejection_is_repaired_once_and_approved() -> None:
    compiler = RecordingCompiler()
    judge = ScriptedJudge(
        {"status": "insufficient_evidence", "reason_code": "unsupported_claim"},
        {"status": "approved"},
    )
    result = run(
        build_graph(
            executor(Demo04Repository(), DETAIL_STEPS), compiler=compiler, judge=judge
        ),
        "2",
    )

    assert _final(result) == ("success", f"Card: {FLUXO[1]}")
    assert len(compiler.calls) == 2
    assert compiler.calls[1]["judge_feedback"] is not None


def test_two_rejections_block_with_the_controlled_sentence() -> None:
    judge = ScriptedJudge(
        {"status": "insufficient_evidence", "reason_code": "unsupported_claim"},
    )
    result = run(
        build_graph(executor(Demo04Repository(), DETAIL_STEPS), judge=judge), "2"
    )

    assert _final(result) == ("clarification_required", JUDGE_BLOCKED_RESPONSE)
    assert len(judge.calls) == 2


def test_missing_evidence_blocks_without_repair() -> None:
    compiler = RecordingCompiler()
    judge = ScriptedJudge(
        {"status": "insufficient_evidence", "reason_code": "missing_evidence"},
    )
    result = run(
        build_graph(
            executor(Demo04Repository(), DETAIL_STEPS), compiler=compiler, judge=judge
        ),
        "2",
    )

    assert _final(result) == ("clarification_required", JUDGE_BLOCKED_RESPONSE)
    assert len(compiler.calls) == 1


def test_jev_outage_returns_the_instability_sentence() -> None:
    judge = ScriptedJudge({"status": "invalid", "error_code": "JUDGE_JEV_UNAVAILABLE"})
    result = run(
        build_graph(executor(Demo04Repository(), DETAIL_STEPS), judge=judge), "2"
    )

    assert _final(result) == ("error", JEV_UNAVAILABLE_RESPONSE)


# State across turns


def test_detail_replaces_the_previous_page_evidence_in_the_checkpoint() -> None:
    repository = Demo04Repository()
    checkpointer = MemorySaver()
    judge = ScriptedJudge()

    run(
        build_graph(
            executor(
                repository, [call("get_suggestion_for_product", product_query="fluxo")]
            ),
            checkpointer=checkpointer,
        ),
        "Busque o produto Fluxo",
        request_id="req-1",
        thread_id="conv-1",
    )
    result = run(
        build_graph(
            executor(repository, DETAIL_STEPS), judge=judge, checkpointer=checkpointer
        ),
        "2",
        request_id="req-2",
        thread_id="conv-1",
    )

    assert [item["evidence_id"].split(":")[0] for item in result["evidences"]] == [
        "suggestion-detail"
    ]
    assert len(judge.calls[0]["evidences"]) == 1


def test_tools_receive_the_server_identity() -> None:
    repository = Demo04Repository()
    run(
        build_graph(
            executor(
                repository, [call("get_suggestion_for_product", product_query="fluxo")]
            )
        ),
        "Busque o produto Fluxo",
    )

    assert {
        (item.user_id, item.role_code, item.store_ids) for item in repository.contexts
    } == {(7, "MANAGER", (STORE_ID,))}


# HTTP


class _NoTraces:
    def save_trace(self, trace: dict[str, Any]) -> None:
        pass


@pytest.mark.parametrize(
    ("steps", "status", "fragment"),
    [
        (
            [call("get_suggestion_for_product", product_query="Arroz Tipo 1")],
            "success",
            "Arroz Tipo 1 Fluxo 5kg",
        ),
        (
            [call("get_suggestion_for_product", product_query="fluxo")],
            "clarification_required",
            "1. Agua de Coco Fluxo 1L",
        ),
        (
            [call("get_suggestion_for_product", product_query="chocolate")],
            "clarification_required",
            "Não há sugestões válidas",
        ),
        (
            [call("list_suggestions", suggestion_type="ORDER", page=0)],
            "error",
            UNAVAILABLE,
        ),
    ],
)
def test_http_maps_each_outcome(steps: list[Step], status: str, fragment: str) -> None:
    graph = build_graph(executor(Demo04Repository(), steps))
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    app.dependency_overrides[get_trace_repository] = _NoTraces
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(
            user_id=7,
            email="manager@example.test",
            role_code="MANAGER",
            store_ids=(STORE_ID,),
        )
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/conversations/conv-http/messages",
                json={"message": "consulta", "sent_at": "2026-10-23T15:00:00Z"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    assert fragment in body["response"]
    assert "candidate-" not in body["response"]
