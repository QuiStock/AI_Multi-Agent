from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from src import config
from src.agents.registry import get_agent_card
from src.agents.schemas.tool_binding import ToolBinding
from src.api.schemas.observability import LabRunRequest, LabRunResponse
from src.api.services.lab_agent_config_service import LabAgentNotFoundError
from src.observability.usage.ai_usage import invoke_with_usage
from src.observability.usage.ai_usage_repository import MongoAIUsageRepository


class UnsupportedLabModelError(ValueError):
    """Raised when a request selects a model outside the configured catalog."""


class LabModelInvocationError(RuntimeError):
    """Raised when the selected model cannot return a textual result."""


class LabRunService:
    """Invoke one configured chat model with an editable prompt and history."""

    def __init__(
        self,
        *,
        model_resolver: Callable[[str], Runnable[Any, Any]],
        usage_repository: MongoAIUsageRepository | None = None,
    ) -> None:
        self._model_resolver = model_resolver
        self._usage_repository = usage_repository

    def _resolve_model(self, request: LabRunRequest) -> Runnable[Any, Any]:
        try:
            model = self._model_resolver(request.model_id.strip())
        except ValueError as exc:
            raise UnsupportedLabModelError from exc

        return model

    def _invoke(self, request: LabRunRequest, model: Runnable[Any, Any]) -> Any:
        messages: list[Any] = [SystemMessage(content=request.prompt)]
        for message in request.messages:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))

        try:
            model_response = invoke_with_usage(
                model,
                messages,
                repository=self._usage_repository,
                source="lab",
                model_name=request.model_id.strip() or config.OPENAI_MODEL,
            )
        except Exception as exc:
            raise LabModelInvocationError from exc

        return model_response

    @staticmethod
    def _text(model_response: Any) -> str:
        content = getattr(model_response, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_blocks = [
                block["text"]
                for block in content
                if isinstance(block, Mapping)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            if text_blocks:
                return "".join(text_blocks)
        raise LabModelInvocationError("O modelo não retornou conteúdo textual")

    def run(self, request: LabRunRequest) -> str:
        return self._text(self._invoke(request, self._resolve_model(request)))

    def preview(self, request: LabRunRequest) -> LabRunResponse:
        """Ask for a tool decision using schemas only; never execute a tool."""
        try:
            card = get_agent_card(request.agent_id or "")
        except ValueError as exc:
            raise LabAgentNotFoundError from exc
        model = self._resolve_model(request)
        schemas = [tool_schema(tool) for tool in card.tools]
        if schemas:
            bind_tools = getattr(model, "bind_tools", None)
            if not callable(bind_tools):
                raise LabModelInvocationError("Modelo sem suporte a tools")
            try:
                model = bind_tools(schemas)
            except Exception as exc:
                raise LabModelInvocationError from exc
        response = self._invoke(request, model)
        raw_calls = getattr(response, "tool_calls", [])
        if not isinstance(raw_calls, list):
            raise LabModelInvocationError("Tool calls inválidas")
        allowed = {tool.name for tool in card.tools}
        calls: list[dict[str, Any]] = []
        for call in raw_calls:
            if (
                not isinstance(call, Mapping)
                or call.get("name") not in allowed
                or not isinstance(call.get("args"), dict)
            ):
                raise LabModelInvocationError("Tool call fora do card")
            calls.append(
                {"name": call["name"], "arguments": call["args"], "id": call.get("id")}
            )
        content = getattr(response, "content", None)
        text = "" if calls and content in (None, []) else self._text(response)
        return LabRunResponse(result=text, tool_calls=calls)


def tool_schema(tool: ToolBinding) -> dict[str, Any]:
    """Translate immutable card metadata without constructing tool executors."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for prop in tool.properties:
        value: dict[str, Any] = {"type": prop.type, "description": prop.description}
        if prop.enum is not None:
            value["enum"] = prop.enum
        if prop.type == "array":
            value["items"] = {"type": prop.items_type or "string"}
        properties[prop.name] = value
        if prop.required:
            required.append(prop.name)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
