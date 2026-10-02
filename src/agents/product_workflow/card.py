from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import EvidencePolicy, MemoryPolicy
from src.agents.schemas.tool_binding import ToolBinding, ToolProperty

from .product_workflow_prompt import PRODUCT_WORKFLOW_PROMPT

PRODUCT_WORKFLOW_CARD = AgentCard(
    id="product_workflow",
    name="Product Workflow",
    description="Explica cards de sugestões de produtos com evidências autorizadas.",
    role=AgentRole.PRODUCT_WORKFLOW,
    version="1.0.0",
    system_prompt_template=PRODUCT_WORKFLOW_PROMPT,
    tools=[
        ToolBinding(
            id="product_card_lookup",
            name="product_card_lookup",
            description="Busca card atual de produto no escopo autorizado do usuário.",
            properties=[
                ToolProperty(
                    name="product_query",
                    type="string",
                    description="Nome ou descrição curta do produto",
                    required=True,
                )
            ],
        )
    ],
    memory_policy=MemoryPolicy(enabled=False, mode="none", max_items=0),
    evidence_policy=EvidencePolicy(
        requires_citations=True, requires_evidence=True, minimum_sources=1
    ),
    tags=["product", "suggestion", "consultative"],
    routing_intents=["product_workflow"],
)
