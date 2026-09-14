from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import (
    EvidencePolicy,
    MemoryPolicy,
)

from .router_prompt import ROUTER_SYSTEM_PROMPT

ROUTER_CARD = AgentCard(
    id="router",
    name="Router Agent",
    description="Classifica a intenção da solicitação.",
    role=AgentRole.ROUTER,
    version="1.0.0",
    system_prompt_template=ROUTER_SYSTEM_PROMPT,
    tools=[],
    memory_policy=MemoryPolicy(
        enabled=False,
        mode="none",
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
