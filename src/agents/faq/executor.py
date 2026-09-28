import hashlib
import json
from typing import Any, cast

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.llm_factory import llm_fast

from .card import FAQ_CARD


class FAQExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = FAQ_CARD
        selected_model = llm_fast if model is None else model
        self.agent = create_agent_from_card(
            card=self.card,
            model=selected_model,
        )

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_result = cast(dict[str, Any], self.agent.invoke(state))

        messages = cast(
            list[AnyMessage],
            raw_result.get("messages", []),
        )

        return {
            "answer": self.extract_answer(messages),
            "evidences": self.extract_evidences(messages),
        }

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
