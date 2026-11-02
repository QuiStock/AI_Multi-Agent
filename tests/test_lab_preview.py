import json
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from src.api.schemas.observability import LabRunRequest
from src.api.services.lab_agent_config_service import (
    LabAgentConfigService,
    LabAgentNotFoundError,
)
from src.api.services.lab_run_service import LabModelInvocationError, LabRunService


def request(**updates: Any) -> LabRunRequest:
    return LabRunRequest.model_validate(
        {
            "agent_id": "faq_rag",
            "model_id": "synthetic-model",
            "prompt": "Use the registered FAQ tool.",
            "messages": [{"role": "user", "content": "Synthetic question"}],
            **updates,
        }
    )


class PreviewModel:
    def __init__(self, name: str = "faq_search") -> None:
        self.schemas: list[dict[str, Any]] = []
        self.name = name
        self.invocations = 0

    def bind_tools(self, schemas: list[dict[str, Any]]) -> Any:
        self.schemas = schemas
        json.dumps(schemas)  # Executable tools/callables cannot be serialized here.
        return RunnableLambda(self.respond)

    def respond(self, _: Any) -> AIMessage:
        self.invocations += 1
        return AIMessage(
            content=[],
            tool_calls=[
                {
                    "name": self.name,
                    "args": {"query": "Synthetic question"},
                    "id": "synthetic-call",
                }
            ],
        )


def test_preview_accepts_frontend_agent_id_and_returns_tool_decision_only():
    model = PreviewModel()
    service = LabRunService(model_resolver=lambda _: cast(Any, model))
    response = service.preview(request())
    assert model.invocations == 1
    assert response.result == ""
    assert response.tool_calls == [
        {
            "name": "faq_search",
            "arguments": {"query": "Synthetic question"},
            "id": "synthetic-call",
        }
    ]
    assert model.schemas[0]["function"]["parameters"]["required"] == ["query"]
    assert model.schemas[0]["function"]["name"] == "faq_search"


def test_preview_rejects_tool_not_declared_in_the_registered_card():
    model = PreviewModel("unregistered_tool")
    service = LabRunService(model_resolver=lambda _: cast(Any, model))
    with pytest.raises(LabModelInvocationError):
        service.preview(request())


def test_preview_rejects_unknown_agents_before_invoking_a_model():
    def forbidden(_: str) -> Any:
        raise AssertionError("A model must not be invoked")

    with pytest.raises(LabAgentNotFoundError):
        LabRunService(model_resolver=forbidden).preview(
            request(agent_id="not_registered")
        )


def test_legacy_textual_lab_request_remains_supported():
    model = RunnableLambda(lambda _: AIMessage(content="Synthetic answer"))
    service = LabRunService(model_resolver=lambda _: model)
    assert service.run(request(agent_id=None)) == "Synthetic answer"


def test_frontend_receives_registered_tool_metadata_and_cannot_inject_tools():
    response = LabAgentConfigService().get_agent_config("faq_rag")
    assert response.tools[0]["id"] == "faq_search"
    with pytest.raises(ValidationError):
        request(tools=[{"name": "unregistered_tool"}])
