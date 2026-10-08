from __future__ import annotations

from src.agents.registry import get_agent_card
from src.api.schemas.observability import LabAgentConfigResponse


class LabAgentNotFoundError(LookupError):
    """Raised when the requested agent is not registered."""


class LabAgentConfigService:
    """Read the registered agent metadata and prompt for the lab."""

    def get_agent_config(self, agent_id: str) -> LabAgentConfigResponse:
        try:
            card = get_agent_card(agent_id)
        except ValueError as exc:
            raise LabAgentNotFoundError from exc

        return LabAgentConfigResponse(
            agent_id=card.id,
            name=card.name,
            description=card.description,
            role=card.role.value,
            version=card.version,
            system_prompt=card.system_prompt_template,
        )
