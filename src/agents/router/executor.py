from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, SystemMessage

from src.agents.router.card import ROUTER_CARD
from src.graphs.contracts import RouteDecision
from src.graphs.state import RoutingDecision
from src.llm_factory import get_structured_model


class RouterExecutor:
    def __init__(self, model: Any | None = None) -> None:
        self.card = ROUTER_CARD
        self.model = model or get_structured_model(RouteDecision)

    @staticmethod
    def _normalize_decision(
        decision: RouteDecision,
    ) -> RoutingDecision:
        if decision.route == "faq":
            return {
                "route": "faq",
                "target_agent": "faq",
                "outcome": "dispatch",
                "reason": decision.reason,
            }
        if decision.route == "clarification_required":
            return {
                "route": "clarification_required",
                "target_agent": None,
                "outcome": "clarification_required",
                "reason": decision.reason,
            }
        return {
            "route": "out_of_scope",
            "target_agent": None,
            "outcome": "out_of_scope",
            "reason": decision.reason,
        }

    def invoke(
        self,
        messages: Sequence[AnyMessage],
    ) -> RoutingDecision:
        try:
            decision = self.model.invoke(
                [
                    SystemMessage(content=self.card.system_prompt_template),
                    *messages,
                ]
            )

            if not isinstance(decision, RouteDecision):
                decision = RouteDecision.model_validate(decision)

        except Exception:
            decision = RouteDecision(
                route="clarification_required",
                reason=("Não foi possível classificar a solicitação com segurança."),
            )
        return self._normalize_decision(decision)
