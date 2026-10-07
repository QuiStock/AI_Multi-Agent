import hashlib
import json
from typing import Any, cast

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.faq.tools.faq_tool import create_faq_search_tool
from src.llm_factory import llm_groq

from .card import FAQ_CARD


class FAQExecutor:
    def __init__(
        self,
        *,
        retriever: QdrantRetriever,
        model: Any | None = None,
        agent_factory: Any | None = None,
    ) -> None:
        self.card = FAQ_CARD
        self.retriever = retriever
        self.model = llm_groq if model is None else model
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
        agent = self.agent_factory(
            card=self.card,
            model=self.model,
            tools=[search_tool],
        )
        raw_result = cast(
            dict[str, Any],
            agent.invoke({"messages": state.get("messages", [])}),
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
        if role_id == 2:
            return ("shared", "manager")
        if role_id == 3:
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
