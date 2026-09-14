from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import (
    EvidencePolicy,
    MemoryPolicy,
)
from src.agents.schemas.tool_binding import (
    ToolBinding,
    ToolProperty,
)

from .faq_prompt import FAQ_SYSTEM_PROMPT

FAQ_CARD = AgentCard(
    id="faq_rag",
    name="FAQ/RAG Agent",
    description=(
        "Responde perguntas usando exclusivamente a base documental do sistema."
    ),
    role=AgentRole.FAQ_RAG,
    version="1.0.0",
    system_prompt_template=FAQ_SYSTEM_PROMPT,
    tools=[
        ToolBinding(
            id="faq_search",
            name="faq_search",
            description=(
                "Realiza a busca de informações com base na base de "
                "conhecimento cadastrada."
            ),
            properties=[
                ToolProperty(
                    name="query",
                    type="string",
                    description="Pergunta que será pesquisada.",
                    required=True,
                ),
            ],
            skip_compilation=False,
        )
    ],
    memory_policy=MemoryPolicy(
        enabled=False,
        mode="none",
        max_items=0,
        ttl_hours=None,
    ),
    evidence_policy=EvidencePolicy(
        requires_citations=True, requires_evidence=True, minimum_sources=1
    ),
    tags=["faq", "rag", "documentos"],
    routing_intents=["faq", "politicas", "processos"],
)
