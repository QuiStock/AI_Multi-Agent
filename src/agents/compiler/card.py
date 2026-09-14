from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import (
    EvidencePolicy,
    MemoryPolicy,
)

from .compiler_prompt import COMPILER_SYSTEM_PROMPT

COMPILER_CARD = AgentCard(
    id="compiler",
    name="Compiler Agent",
    description="Sintetiza a resposta final para o usuário.",
    role=AgentRole.RESPONSE_COMPILER,
    version="1.0.0",
    system_prompt_template=COMPILER_SYSTEM_PROMPT,
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
    tags=["compiler", "answer"],
    routing_intents=[
        "resposta",
        "síntese de resposta",
    ],
)
