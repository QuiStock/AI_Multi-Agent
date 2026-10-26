from src.agents.schemas.agent_card import AgentCard, AgentRole
from src.agents.schemas.tool_binding import ToolBinding, ToolProperty

from .product_workflow_prompt import PRODUCT_WORKFLOW_SYSTEM_PROMPT

PRODUCT_WORKFLOW_CARD = AgentCard(
    id="product_workflow",
    name="Product Workflow Agent",
    description="Consulta e explica sugestões comerciais sem alterar o domínio.",
    role=AgentRole.PRODUCT_WORKFLOW,
    version="1.0.0",
    system_prompt_template=PRODUCT_WORKFLOW_SYSTEM_PROMPT,
    tools=[
        ToolBinding(
            id="get_suggestion_for_product",
            name="get_suggestion_for_product",
            description=(
                "Busca sugestões autorizadas por nome parcial ou SKU e "
                "retorna uma sugestão completa ou candidatos seguros."
            ),
            properties=[
                ToolProperty(
                    name="product_query",
                    type="string",
                    description=(
                        "Nome parcial do produto ou SKU informado pelo usuário."
                    ),
                    required=True,
                ),
                ToolProperty(
                    name="page",
                    type="integer",
                    description=(
                        "Página de 6 sugestões; use 1 na busca inicial e incremente "
                        "quando o usuário pedir a próxima página."
                    ),
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
                "Lista até seis sugestões ORDER ou PROMOTION visíveis ao usuário "
                "autenticado."
            ),
            properties=[
                ToolProperty(
                    name="suggestion_type",
                    type="array",
                    items_type="string",
                    description=(
                        "Um ou os dois tipos, ORDER e PROMOTION. "
                        "Passe os dois quando o usuário não especificar o tipo."
                    ),
                    required=True,
                    enum=["ORDER", "PROMOTION"],
                ),
                ToolProperty(
                    name="page",
                    type="integer",
                    description=(
                        "Página de 6 sugestões; use 1 na busca inicial e incremente "
                        "quando o usuário pedir a próxima página."
                    ),
                ),
            ],
        ),
        ToolBinding(
            id="get_promotion_by_expiration",
            name="get_promotion_by_expiration",
            description=(
                "Encontra promoções pela validade extrema ou até uma data "
                "informada, com no máximo seis itens por página."
            ),
            properties=[
                ToolProperty(
                    name="direction",
                    type="string",
                    description=(
                        "nearest para a validade mais próxima ou longest para a "
                        "mais distante. Omita quando until for informado."
                    ),
                    enum=["nearest", "longest"],
                ),
                ToolProperty(
                    name="until",
                    type="string",
                    description=(
                        "Data AAAA-MM-DD. Lista promoções válidas entre a data "
                        "da mensagem e essa data, inclusive."
                    ),
                ),
                ToolProperty(
                    name="page",
                    type="integer",
                    description=(
                        "Página de 6 sugestões; use 1 na busca inicial e incremente "
                        "quando o usuário pedir a próxima página."
                    ),
                ),
            ],
        ),
    ],
)
