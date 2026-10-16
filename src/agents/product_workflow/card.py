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
                "Busca sugestões autorizadas por nome, SKU ou identificador e "
                "retorna uma sugestão completa ou candidatos seguros."
            ),
            properties=[
                ToolProperty(
                    name="product_query",
                    type="string",
                    description=(
                        "Nome, SKU, product_id ou suggestion_id informado pelo usuário."
                    ),
                    required=True,
                ),
            ],
        ),
        ToolBinding(
            id="get_suggestion_detail",
            name="get_suggestion_detail",
            description=(
                "Retorna o card da seleção escolhida após revalidar escopo, "
                "cargo, status e expiração."
            ),
            properties=[
                ToolProperty(
                    name="selection_id",
                    type="string",
                    description="Identificador de seleção retornado pelos candidatos.",
                    required=True,
                )
            ],
        ),
        ToolBinding(
            id="list_suggestions",
            name="list_suggestions",
            description=(
                "Lista sugestões ORDER ou PROMOTION visíveis ao usuário "
                "autenticado, com paginação e resumo numerado."
            ),
            properties=[
                ToolProperty(
                    name="suggestion_type",
                    type="string",
                    description="Tipo a listar: ORDER ou PROMOTION.",
                    required=True,
                    enum=["ORDER", "PROMOTION"],
                ),
                ToolProperty(
                    name="page_size",
                    type="integer",
                    description="Quantidade de itens por página (máximo 50).",
                ),
                ToolProperty(
                    name="cursor",
                    type="string",
                    description="Cursor devolvido pela página anterior.",
                ),
            ],
        ),
        ToolBinding(
            id="get_promotion_by_expiration",
            name="get_promotion_by_expiration",
            description=(
                "Encontra promoções com a validade mais próxima ou mais "
                "distante e apresenta empates para escolha."
            ),
            properties=[
                ToolProperty(
                    name="direction",
                    type="string",
                    description="nearest para mais próxima ou longest para mais distante.",
                    required=True,
                    enum=["nearest", "longest"],
                ),
                ToolProperty(
                    name="page_size",
                    type="integer",
                    description="Quantidade de empatados por página (máximo 50).",
                ),
                ToolProperty(
                    name="cursor",
                    type="string",
                    description="Cursor devolvido pela página anterior.",
                ),
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
