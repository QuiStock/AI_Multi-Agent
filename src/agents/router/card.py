from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import (
    EvidencePolicy,
    MemoryPolicy,
)
from src.agents.schemas.tool_binding import ToolBinding

from .router_prompt import ROUTER_SYSTEM_PROMPT

ROUTER_CARD = AgentCard(
    id="router",
    name="Router Agent",
    description="Classifica a intenção da solicitação.",
    role=AgentRole.ROUTER,
    version="1.0.0",
    system_prompt_template=ROUTER_SYSTEM_PROMPT,
    tools=[
        ToolBinding(
            id="search_conversation_summaries",
            name="Buscar resumos de conversas anteriores",
            description=(
                "Busca resumos semanticamente próximos da mensagem atual, "
                "usando identidade autenticada fornecida pelo runtime."
            ),
        )
    ],
    memory_policy=MemoryPolicy(
        enabled=True,
        mode="long_term",
        max_items=3,
    ),
    evidence_policy=EvidencePolicy(
        requires_evidence=False,
        requires_citations=False,
        minimum_sources=0,
    ),
    tags=["router", "classification"],
    routing_intents=[
        "faq",
        "clarification_required",
        "out_of_scope",
    ],
)
