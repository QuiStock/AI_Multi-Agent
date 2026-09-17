from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import (
    EvidencePolicy,
    FailurePolicy,
    MemoryPolicy,
)

from .judge_prompt import JUDGE_SYSTEM_PROMPT

JUDGE_CARD = AgentCard(
    id="evidence_judge",
    name="Evidence Judge Agent",
    description=(
        "Valida a resposta compilada contra as evidências disponíveis, "
        "verificando groundedness, consistência e contradições."
    ),
    role=AgentRole.EVIDENCE_JUDGE,
    version="1.0.0",
    system_prompt_template=JUDGE_SYSTEM_PROMPT,
    tools=[],
    memory_policy=MemoryPolicy(
        enabled=False,
        mode="none",
        max_items=0,
        ttl_hours=None,
    ),
    evidence_policy=EvidencePolicy(
        requires_evidence=True,
        requires_citations=False,
        minimum_sources=1,
    ),
    failure_policy=FailurePolicy(
        on_timeout="fail",
        max_retries=0,
        fallback_message=(
            "Não foi possível validar a resposta com as evidências disponíveis."
        ),
    ),
    tags=[
        "judge",
        "evidence",
        "groundedness",
        "validation",
    ],
    routing_intents=[],
)
