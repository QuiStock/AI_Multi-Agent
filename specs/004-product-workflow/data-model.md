# Data Model — Product Workflow

## Entidades e contratos lógicos

| Entidade | Campos conceituais | Origem/owner | Persistência |
|---|---|---|---|
| CardSnapshot | Identificador do produto quando disponível, nome, categoria e atributos comerciais efetivamente exibidos no card (ex.: quantidade, validade e parâmetro sugerido) | Request do app; `source_type=client_card_snapshot` | Recebido por requisição; persistência somente conforme política de mensagens aprovada |
| ProductCard | Mesmo contrato público do snapshot, com atributos disponíveis e referências internas necessárias para distinguir produto/sugestão | Tool SQL; `source_type=product_card_query` | Resultado transitório da consulta; não criar nova tabela |
| AuthenticatedProductContext | Email validado, role (`2` gerente, `3` funcionário) e lojas permitidas | Dependência de autenticação/SQL no servidor | Efêmero no request/GraphState; nunca aceitar do payload do cliente |
| ProductCandidate | Dados estritamente necessários para distinguir resultado (ex.: nome, categoria e SKU somente se necessários) e referência interna temporária da consulta | Resultado da consulta dentro do escopo autorizado | Transitório no resultado/contexto normal da conversa; não criar armazenamento dedicado |
| Evidence | ID estável, source type, source ID, conteúdo factual e metadata | Snapshot ou tool; reducer do grafo | `GraphState.evidences`; distinguir proveniência |

## Regras e integridade

1. Candidato só pode ser exibido a partir de resultado autorizado para o contexto autenticado atual.
2. Uma escolha textual só identifica a opção; a nova consulta sempre reaplica cargo e escopo de loja do servidor.
3. Se não for possível relacionar a mensagem do usuário a uma opção de forma inequívoca pelo contexto disponível, pedir que identifique o produto; não escolher silenciosamente.
4. A tool retorna no máximo o limite definido no contrato, incluindo casos de ambiguidade. O limite numérico requer validação/definição em tarefas caso não haja parâmetro existente no repositório.
5. `EXPIRED` é uma regra derivada de `suggestion_log`; nomes exatos de PK/FK e associação precisam ser mapeados no SQL anexado antes da implementação.
6. Um registro de domínio ausente resulta em `not_found`; indisponibilidade, timeout ou falha de SQL resulta em erro de dependência.
7. A evidência de snapshot é evidência do que o cliente enviou, não atestado de verdade do banco.

## Mapeamento inicial ao SQL fornecido

- `suggestion(product_id, store_id)` é a origem do estado/parametrização sugeridos; `suggestion_log(suggestion_id, event)` exclui itens com evento `EXPIRED`.
- `product(id, name, sku, category_id)` e `category(id, name)` identificam o produto; `store(id, name)` representa o estabelecimento.
- `user_account(id, email, role_id)` e `user_store(user_id, store_id, active, unassigned_at)` são parte do contexto/escopo. A consulta deve reutilizar a identidade autenticada e validar vínculo de loja ativo.
- Para cards do tipo pedido, a quantidade vem de `current_batch_count` com fallback `ml_batch_count`; para promoção, percentual vem de `current_discount_percentage` com fallback `ml_discount_percentage`, além dos preços/validade da promoção existentes.
- A validade física exibida no card vem do menor `batch.expiration_date` para o produto e loja, somente entre lotes ativos com saldo positivo. Não confundir com `suggestion.promotion_valid_until`. Essa agregação precisa ser confrontada com o card real do frontend antes de produção.
- O script não apresenta campo explícito de apresentação/embalagem em `product`; existem `sku` e `erp_id`. Se nome e categoria não bastarem para distinguir homônimos, usar SKU como identificador, sem rotulá-lo como apresentação.

## Persistência

Não criar entidade, campo Mongo ou mecanismo especial para opções aguardando escolha. A seleção usa o contexto comum disponível na conversa. Se esse contexto não estiver disponível, pedir que o usuário identifique o produto outra vez.
