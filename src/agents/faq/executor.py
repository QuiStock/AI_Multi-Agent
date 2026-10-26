import json
from collections.abc import Sequence
from typing import Any

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.agents.faq.contracts import FaqResponse
from src.agents.faq.ingestion.audience import Audience
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever
from src.agents.faq.tools.faq_tool import create_faq_search_tool
from src.agents.faq.tools.schemas import FAQSearchData
from src.agents.schemas.tool_call import ToolCalled
from src.agents.schemas.tool_result import ToolResult
from src.llm_factory import llm_openai

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
        self.model = llm_openai if model is None else model
        self.agent_factory = (
            create_agent_from_card if agent_factory is None else agent_factory
        )

    def invoke(
        self,
        *,
        messages: Sequence[AnyMessage],
        allowed_audiences: Sequence[Audience],
        request_id: str,
        trace_id: str,
    ) -> FaqResponse:
        captured: dict[str, Any] | None = None

        def capture(payload: dict[str, Any]) -> None:
            nonlocal captured
            captured = payload

        try:
            search_tool = create_faq_search_tool(
                self.retriever,
                allowed_audiences=allowed_audiences,
                request_id=request_id,
                trace_id=trace_id,
                on_result=capture,
            )
            runtime_card = self.card.model_copy(
                update={
                    "tools": [
                        binding
                        for binding in self.card.tools
                        if search_tool.name == binding.id
                    ]
                }
            )
            agent = self.agent_factory(
                card=runtime_card,
                model=self.model,
                tools=[search_tool],
            )
        except Exception:
            return self._failure("FAQ_AGENT_SETUP_FAILED")

        try:
            raw_result = agent.invoke({"messages": list(messages)})
        except Exception:
            return self._failure(
                "FAQ_AGENT_UNAVAILABLE",
                tool_called=self._tool_called(captured) if captured else None,
            )

        raw_messages = (
            raw_result.get("messages", []) if isinstance(raw_result, dict) else []
        )
        messages = raw_messages if isinstance(raw_messages, list) else []
        tool_payload = captured or self.extract_tool_payload(messages)
        if tool_payload is None:
            return self._failure("FAQ_TOOL_NOT_CALLED")

        if not self.is_valid_tool_payload(tool_payload):
            return self._failure(
                "FAQ_INVALID_RESULT",
                tool_called=self._tool_called(tool_payload),
            )

        tool_called = self._tool_called(tool_payload)
        answer = self.extract_answer(messages)
        if not answer:
            return self._failure(
                "FAQ_EMPTY_RESPONSE",
                tool_called=tool_called,
            )

        return {
            "status": "success",
            "answer": answer,
            "tool_called": tool_called,
        }

    @staticmethod
    def _failure(
        code: str,
        *,
        tool_called: ToolCalled[dict[str, Any]] | None = None,
    ) -> FaqResponse:
        response: FaqResponse = {
            "status": "error",
            "answer": "",
            "error_code": code,
        }
        if tool_called is not None:
            response["tool_called"] = tool_called
        return response

    @staticmethod
    def _tool_called(payload: dict[str, Any]) -> ToolCalled[dict[str, Any]]:
        valid = FAQExecutor.is_valid_tool_payload(payload)
        tool_result_status = payload.get("status")
        return {
            "tool_name": "faq_search",
            "status": (
                "success"
                if valid and tool_result_status in {"success", "partial"}
                else "error"
            ),
            "toolResult": payload,
        }

    @staticmethod
    def extract_answer(messages: list[AnyMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                content = _plain_text(message.content)
                if content:
                    return content
        return ""

    @staticmethod
    def extract_tool_payload(messages: list[AnyMessage]) -> dict[str, Any] | None:
        tool_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, ToolMessage) and message.name == "faq_search"
            ),
            None,
        )
        if tool_message is None or not isinstance(tool_message.content, str):
            return None
        try:
            payload = json.loads(tool_message.content)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def is_valid_tool_payload(payload: dict[str, Any]) -> bool:
        try:
            result = ToolResult[Any].model_validate(payload)
            if result.meta.tool_name != "faq_search":
                return False
            if result.status.value == "error":
                return True
            FAQSearchData.model_validate(result.data)
        except Exception:
            return False
        return True


def _plain_text(content: object) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
            else:
                value = getattr(block, "text", None)
                if isinstance(value, str):
                    parts.append(value)
        text = "".join(parts).strip()
    else:
        text = ""
    if text.startswith("[{") and "type" in text[:80]:
        return ""
    return text
