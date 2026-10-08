from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.policies import FailurePolicy
from src.agents.schemas.tool_binding import ToolBinding, ToolProperty

from .product_workflow_prompt import PRODUCT_WORKFLOW_SYSTEM_PROMPT

PRODUCT_WORKFLOW_CARD = AgentCard(
    id="product_workflow",
    name="Product Workflow Agent",
    description=(
        "Consulta e explica sugestões e triagem comercial sem alterar o domínio."
    ),
    role=AgentRole.PRODUCT_WORKFLOW,
    version="1.0.0",
    system_prompt_template=PRODUCT_WORKFLOW_SYSTEM_PROMPT,
    tools=[
        ToolBinding(
            id="get_suggestion_for_product",
            name="get_suggestion_for_product",
            description=(
                "Busca sugestões autorizadas por nome, SKU ou categoria e "
                "retorna candidatos numerados."
            ),
            properties=[
                ToolProperty(
                    name="product_query",
                    type="string",
                    description="Nome, SKU ou categoria informada pelo usuário.",
                    required=True,
                ),
            ],
        ),
        ToolBinding(
            id="get_suggestion_detail",
            name="get_suggestion_detail",
            description=(
                "Retorna o card da sugestão escolhida e, para gerente, "
                "os dados da triagem."
            ),
            properties=[
                ToolProperty(
                    name="selection_ref",
                    type="string",
                    description="Referência retornada pela busca do produto.",
                    required=True,
                )
            ],
        ),
    ],
    failure_policy=FailurePolicy(
        on_timeout="fail",
        max_retries=0,
        fallback_message="Não foi possível consultar o fluxo de produtos agora.",
    ),
    tags=["product_workflow", "read_only", "suggestions", "triage"],
    routing_intents=["product_workflow", "suggestions"],
)
