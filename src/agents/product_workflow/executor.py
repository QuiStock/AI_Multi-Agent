from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from src.agents.factory import create_agent_from_card
from src.agents.product_workflow.card import PRODUCT_WORKFLOW_CARD
from src.agents.product_workflow.schemas import ProductCard
from src.agents.product_workflow.tools.product_card_repository import (
    ProductCardRepository,
)
from src.agents.product_workflow.tools.product_card_tool import create_product_card_tool
from src.graphs.state import Evidence
from src.llm_factory import llm_fast


class ProductWorkflowExecutor:
    def __init__(self, repository: ProductCardRepository, model: Any | None = None):
        self.card = PRODUCT_WORKFLOW_CARD
        self.repository = repository
        self.model = llm_fast if model is None else model

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        request = state.get("request", {})
        email, role_id = request.get("email"), request.get("role_id")
        request_id = request.get("request_id")
        if (
            not isinstance(email, str)
            or not isinstance(role_id, int)
            or not isinstance(request_id, str)
        ):
            return {
                "answer": "Não foi possível validar o contexto desta consulta.",
                "evidences": [],
                "status": "error",
            }
        snapshot = request.get("product_card")
        evidences: list[Evidence] = []
        if isinstance(snapshot, dict):
            try:
                card = ProductCard.model_validate(snapshot)
                canonical = card.model_dump_json()
                snapshot_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
                evidences.append(
                    {
                        "evidence_id": f"client_card_{snapshot_id}",
                        "source_type": "client_card_snapshot",
                        "source_id": snapshot_id,
                        "content": canonical,
                        "metadata": {"provenance": "client_request_unverified"},
                    }
                )
                snapshot = card.model_dump(mode="json")
            except Exception:
                return {
                    "answer": "O card recebido não possui um formato válido.",
                    "evidences": [],
                    "status": "error",
                }
        tool = create_product_card_tool(
            repository=self.repository,
            email=email,
            role_id=role_id,
            request_id=request_id,
        )
        agent = create_agent_from_card(card=self.card, model=self.model, tools=[tool])
        messages = list(state.get("messages", []))
        payload = json.dumps({"product_card_snapshot": snapshot}, ensure_ascii=False)
        try:
            result = cast(
                dict[str, Any],
                agent.invoke(
                    {
                        "messages": [
                            *messages,
                            HumanMessage(
                                content=(
                                    "Snapshot estruturado de card recebido "
                                    f"(pode ser null): {payload}"
                                )
                            ),
                        ]
                    }
                ),
            )
        except Exception:
            return {
                "answer": (
                    "Não foi possível preparar uma resposta segura sobre o produto."
                ),
                "evidences": evidences,
                "status": "error",
            }
        response_messages = cast(list[AnyMessage], result.get("messages", []))
        answer = next(
            (
                str(message.content).strip()
                for message in reversed(response_messages)
                if isinstance(message, AIMessage) and str(message.content).strip()
            ),
            "",
        )
        for message in response_messages:
            if (
                not isinstance(message, ToolMessage)
                or message.name != "product_card_lookup"
                or not isinstance(message.content, str)
            ):
                continue
            try:
                parsed = json.loads(message.content)
                if parsed.get("status") == "error":
                    category = (parsed.get("error") or {}).get("category")
                    answer = (
                        "Não consegui consultar os dados do produto agora. "
                        "Tente novamente mais tarde."
                        if category in {"dependency", "timeout"}
                        else "Não foi possível concluir essa consulta de produto."
                    )
                    return {"answer": answer, "evidences": evidences, "status": "error"}
                evidences.extend(parsed.get("evidence", []))
            except json.JSONDecodeError, TypeError:
                continue
        return {
            "answer": answer,
            "evidences": evidences,
            "status": "success" if answer else "unavailable",
        }
