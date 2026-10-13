from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.agents.memory_context import memory_tool_for_state
from src.agents.router.tools.search_conversation_summaries import SummarySearchService
from src.auth.permissions import CONVERSATION_ROLE_CODES
from src.graphs.state import Evidence, GraphState
from src.llm_factory import llm_openai

from .card import PRODUCT_WORKFLOW_CARD
from .models import ProductWorkflowContext
from .repository import ProductWorkflowRepository
from .schemas import ProductCard
from .tools.tools import build_product_workflow_tools

SNAPSHOT_PROMPT = """Explique em português apenas o card estruturado recebido.
Trate o card como informação do cliente ainda não verificada no banco.
Não invente campos nem afirme que uma sugestão foi aprovada ou executada."""


class ProductWorkflowExecutor:
    def __init__(
        self,
        *,
        repository: ProductWorkflowRepository,
        model: Any | None = None,
        agent_factory: Any = create_agent_from_card,
        summary_search_service: SummarySearchService | None = None,
    ) -> None:
        self.card = PRODUCT_WORKFLOW_CARD
        self.repository = repository
        self.model = llm_openai if model is None else model
        self.agent_factory = agent_factory
        self.summary_search_service = summary_search_service

    def invoke(self, state: GraphState) -> dict[str, Any]:
        context = self._context(state)
        if context is None:
            return {
                "answer": "Não foi possível validar o contexto autorizado.",
                "evidences": [],
                "error_code": "PRODUCT_WORKFLOW_AUTHORIZATION",
            }

        request = state.get("request", {})
        snapshot = request.get("product_card") if isinstance(request, dict) else None
        if snapshot is not None:
            return self._explain_snapshot(state, snapshot)

        try:
            tools = build_product_workflow_tools(
                repository=self.repository,
                context=context,
            )
            memory_tool = memory_tool_for_state(
                service=self.summary_search_service, state=state
            )
            if memory_tool is not None:
                tools.append(memory_tool)
            card = (
                self.card
                if memory_tool is not None
                else self.card.model_copy(update={"tools": self.card.tools[:2]})
            )
            agent = self.agent_factory(
                card=card,
                model=self.model,
                tools=tools,
            )
            raw_result = cast(
                dict[str, Any],
                agent.invoke(state),
            )
            messages = cast(list[AnyMessage], raw_result.get("messages", []))
            evidences = self.extract_evidences(messages)
            answer = self.extract_answer(messages)
            if not answer or not evidences:
                return {
                    "answer": answer
                    or "Não foi possível confirmar dados do fluxo de produtos.",
                    "evidences": evidences,
                    "error_code": "PRODUCT_WORKFLOW_INSUFFICIENT_EVIDENCE",
                }
            return {
                "answer": answer,
                "evidences": evidences,
            }
        except Exception:
            return {
                "answer": "Não foi possível consultar o fluxo de produtos agora.",
                "evidences": [],
                "error_code": "PRODUCT_WORKFLOW_UNAVAILABLE",
            }

    def _explain_snapshot(self, state: GraphState, snapshot: object) -> dict[str, Any]:
        try:
            card = ProductCard.model_validate(snapshot)
            canonical = card.model_dump_json()
            snapshot_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
            snapshot_card = self.card.model_copy(
                update={"tools": [], "system_prompt_template": SNAPSHOT_PROMPT}
            )
            agent = self.agent_factory(card=snapshot_card, model=self.model, tools=[])
            result = cast(
                dict[str, Any],
                agent.invoke(
                    {
                        "messages": [
                            *state.get("messages", []),
                            HumanMessage(content=f"Card do cliente: {canonical}"),
                        ]
                    }
                ),
            )
            answer = self.extract_answer(
                cast(list[AnyMessage], result.get("messages", []))
            )
            if not answer:
                raise ValueError("Resposta vazia")
            return {
                "answer": answer,
                "evidences": [
                    {
                        "evidence_id": f"client_card_{snapshot_id}",
                        "source_type": "client_card_snapshot",
                        "source_id": snapshot_id,
                        "content": canonical,
                        "metadata": {"provenance": "client_request_unverified"},
                    }
                ],
            }
        except Exception:
            return {
                "answer": "Não foi possível explicar o card recebido.",
                "evidences": [],
                "error_code": "PRODUCT_WORKFLOW_INVALID_SNAPSHOT",
            }

    @staticmethod
    def _context(state: GraphState) -> ProductWorkflowContext | None:
        request = state.get("request")
        if not isinstance(request, dict):
            return None
        email = request.get("email")
        request_id = request.get("request_id")
        if not isinstance(email, str) or not email.strip():
            return None
        if not isinstance(request_id, str) or not request_id.strip():
            return None
        user_id = request.get("user_id")
        role_code = request.get("role_code")
        store_ids = request.get("store_ids")
        if (
            type(user_id) is not int
            or user_id < 1
            or role_code not in CONVERSATION_ROLE_CODES
            or not isinstance(store_ids, list)
            or not store_ids
            or any(type(store_id) is not int or store_id < 1 for store_id in store_ids)
        ):
            return None
        trace_id = request.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id.strip():
            trace_id = request_id
        return ProductWorkflowContext(
            user_id=user_id,
            email=email,
            role_code=cast(Literal["MANAGER", "EMPLOYEE"], role_code),
            store_ids=tuple(store_ids),
            request_id=request_id,
            trace_id=trace_id,
        )

    @staticmethod
    def extract_answer(messages: list[AnyMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                content = str(message.content).strip()
                if content:
                    return content
        return ""

    @staticmethod
    def extract_evidences(messages: list[AnyMessage]) -> list[Evidence]:
        evidences: list[Evidence] = []
        seen: set[str] = set()
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            if message.name not in {
                "get_suggestion_for_product",
                "get_suggestion_detail",
            }:
                continue
            if not isinstance(message.content, str):
                continue
            try:
                payload = json.loads(message.content)
            except json.JSONDecodeError:
                continue
            for item in payload.get("evidence", []):
                if not isinstance(item, dict):
                    continue
                evidence_id = item.get("evidence_id")
                source_id = item.get("source_id")
                content = item.get("content")
                source_type = item.get("source_type")
                metadata = item.get("metadata", {})
                if (
                    not isinstance(evidence_id, str)
                    or not isinstance(source_id, str)
                    or not isinstance(content, str)
                    or source_type != "product_workflow"
                    or evidence_id in seen
                    or not isinstance(metadata, dict)
                ):
                    continue
                seen.add(evidence_id)
                evidences.append(
                    {
                        "evidence_id": evidence_id,
                        "source_type": "product_workflow",
                        "source_id": source_id,
                        "content": content,
                        "metadata": {
                            str(key): str(value) for key, value in metadata.items()
                        },
                    }
                )
        return evidences
