import hashlib
import json
from typing import Any, cast

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.faq.tools.faq_tool import create_faq_search_tool
from src.agents.memory_context import memory_tool_for_state
from src.agents.router.tools.search_conversation_summaries import SummarySearchService
from src.graphs.state import GraphState
from src.llm_factory import llm_openai

from .card import FAQ_CARD

MANAGER_ROLE_ID = 2
EMPLOYEE_ROLE_ID = 3


class FAQExecutor:
    def __init__(
        self,
        *,
        retriever: QdrantRetriever,
        model: Any | None = None,
        agent_factory: Any | None = None,
        summary_search_service: SummarySearchService | None = None,
    ) -> None:
        self.card = FAQ_CARD
        self.retriever = retriever
        self.model = llm_openai if model is None else model
        self.summary_search_service = summary_search_service
        self.agent_factory = (
            create_agent_from_card if agent_factory is None else agent_factory
        )

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            allowed_audiences = self._allowed_audiences(state)
        except KeyError, PermissionError, TypeError, ValueError:
            return {
                "answer": "Não foi possível validar o contexto autorizado.",
                "evidences": [],
                "error_code": "FAQ_AUTHORIZATION",
            }

        search_tool = create_faq_search_tool(
            self.retriever,
            allowed_audiences=allowed_audiences,
        )
        graph_state = cast(GraphState, state)
        memory_tool = memory_tool_for_state(
            service=self.summary_search_service, state=graph_state
        )
        tools = [search_tool, *([memory_tool] if memory_tool is not None else [])]
        card = (
            self.card
            if memory_tool is not None
            else self.card.model_copy(update={"tools": self.card.tools[:1]})
        )
        agent = self.agent_factory(
            card=card,
            model=self.model,
            tools=tools,
        )
        raw_result = cast(
            dict[str, Any],
            agent.invoke({"messages": graph_state.get("messages", [])}),
        )

        messages = cast(
            list[AnyMessage],
            raw_result.get("messages", []),
        )

        return {
            "answer": self.extract_answer(messages),
            "evidences": self.extract_evidences(messages),
        }

    @staticmethod
    def _allowed_audiences(state: dict[str, Any]) -> tuple[Audience, ...]:
        request = state.get("request")
        if not isinstance(request, dict):
            raise ValueError("O contexto da requisição é obrigatório.")

        role_id = request.get("role_id")
        if role_id == MANAGER_ROLE_ID:
            return ("shared", "manager")
        if role_id == EMPLOYEE_ROLE_ID:
            return ("shared", "employee")

        raise PermissionError("Role sem acesso ao FAQ.")

    @staticmethod
    def extract_answer(messages: list[AnyMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                content = str(message.content).strip()

                if content:
                    return content

        return ""

    @staticmethod
    def extract_evidences(messages: list[AnyMessage]) -> list[dict[str, Any]]:

        tool_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, ToolMessage) and message.name == "faq_search"
            ),
            None,
        )

        if tool_message is None:
            return []

        if not isinstance(tool_message.content, str):
            return []

        try:
            payload = json.loads(tool_message.content)
        except json.JSONDecodeError:
            return []

        evidences: list[dict[str, Any]] = []

        for item in payload.get("resultados", []):
            source_id = str(item.get("arquivo", "")).strip()
            content = str(item.get("conteudo", "")).strip()

            if not source_id or not content:
                continue

            page = item.get("pagina")
            relevance = item.get("relevancia")

            raw_id = f"{source_id}|{page or ''}|{content}"
            digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]

            metadata = {
                "relevance": str(relevance),
            }

            if page is not None:
                metadata["page"] = str(page)

            evidences.append(
                {
                    "evidence_id": f"faq_{digest}",
                    "source_type": "faq_document",
                    "source_id": source_id,
                    "content": content,
                    "metadata": metadata,
                }
            )

        return evidences
