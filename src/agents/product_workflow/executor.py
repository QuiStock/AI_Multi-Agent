from __future__ import annotations

import json
from typing import Any, cast

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.graphs.state import Evidence, GraphState
from src.llm_factory import llm_groq

from .card import PRODUCT_WORKFLOW_CARD
from .models import ProductWorkflowContext
from .repository import ProductWorkflowRepository
from .tools.tools import build_product_workflow_tools


class ProductWorkflowExecutor:
    def __init__(
        self,
        *,
        repository: ProductWorkflowRepository,
        model: Any | None = None,
        agent_factory: Any = create_agent_from_card,
    ) -> None:
        self.card = PRODUCT_WORKFLOW_CARD
        self.repository = repository
        self.model = llm_groq if model is None else model
        self.agent_factory = agent_factory

    def invoke(self, state: GraphState) -> dict[str, Any]:
        context = self._context(state)
        if context is None:
            return {
                "answer": "Não foi possível validar o contexto autorizado.",
                "evidences": [],
                "error_code": "PRODUCT_WORKFLOW_AUTHORIZATION",
            }

        try:
            tools = build_product_workflow_tools(
                repository=self.repository,
                context=context,
            )
            agent = self.agent_factory(
                card=self.card,
                model=self.model,
                tools=tools,
            )
            raw_result = cast(dict[str, Any], agent.invoke(state))
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
        role_id = request.get("role_id")
        if role_id is not None and not isinstance(role_id, int):
            return None
        trace_id = request.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id.strip():
            trace_id = request_id
        return ProductWorkflowContext(
            email=email,
            role_id=role_id,
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
