# Research — Product Workflow

Este documento registra pesquisa técnica e alternativas para decisões necessárias ao plano. Status `confirmado` vem da especificação/conversa; `proposto` é recomendação de desenho ainda sujeita a revisão.

## R-001 — Fluxo de consulta do card

- **Status**: `confirmado`.
- **Decisão**: o workflow compara o assunto da pergunta com o produto do snapshot estruturado. Pergunta sobre o mesmo card usa o snapshot diretamente e não consulta o PostgreSQL; pergunta sobre outro produto ou sem snapshot usa a tool de consulta.
- **Alternativas**: consultar sempre o banco (rejeitada, viola a decisão de usar o snapshot para o card aberto); responder sobre outro produto apenas com conhecimento do modelo (rejeitada, sem evidência comercial).
- **Consequência**: o agente deve explicitar proveniência dos dados e não misturar valores entre snapshot e resultado da tool.

## R-002 — Consulta comercial

- **Status**: regras e estrutura base `confirmado` pela spec e pelo arquivo `Quistock/quistock-updated.sql`; qualquer atributo adicional além dos campos já disponíveis só será usado se for necessário.
- **Decisão**: tool predefinida, parametrizada e read-only, que monta o mesmo contrato estruturado de card. Cargo e escopo de loja são calculados no servidor; funcionário vê somente `available_for_triage`, gerente somente `SENT_TO_MANAGER`; sugestão com evento relacionado `EXPIRED` em `suggestion_log` é excluída.
- **Mapeamento físico já confirmado no SQL**: `suggestion` referencia `product` por `product_id` e `store` por `store_id`; `suggestion_log.suggestion_id` referencia a sugestão; `product.category_id` referencia `category`; `user_account.role_id` referencia `role`; `user_store` liga usuário e loja com `active`/`unassigned_at`. Campos disponíveis incluem produto `name`/`sku`, categoria `name`, tipo/status da sugestão, parâmetros de pedido/promoção e loja.
- **Limite observado no SQL**: `product` não tem coluna explícita de apresentação/embalagem. Não é necessário buscar ou criar esse dado para a feature; quando homônimos precisarem ser distinguidos, usar apenas campos existentes que resolvam a ambiguidade, por exemplo categoria e, se ainda necessário, SKU.
- **Alternativas**: SQL arbitrário do modelo (rejeitada); busca genérica sem contexto de loja/cargo (rejeitada); alterar schema ou script SQL (fora do escopo confirmado).
- **Consequência**: usar o script fornecido como mapa inicial, verificar divergência entre esse arquivo e o banco/versão real antes de codificar, e mapear cada campo exibido do card à sua fonte. A consulta precisa limitar resultados, aplicar timeout e produzir erro distinto de “não encontrado”.

## R-003 — Evidência do juiz

- **Status**: `confirmado`.
- **Decisão**: snapshot do cliente e resultado do banco são evidências utilizáveis para avaliar suporte textual, porém com proveniência distinta. O juiz verifica se a resposta é sustentada pelo payload disponível; não autentica a veracidade externa do snapshot.
- **Alternativas**: descartar snapshot como evidência (rejeitada, impede responder ao botão de ajuda sem consulta); confiar em qualquer alegação do agente (rejeitada, contradiz groundedness).
- **Consequência**: IDs de evidência únicos e metadados `source_type`/origem devem permitir ao juiz e à auditoria distinguir `client_card_snapshot` de consulta comercial. Não incluir atributos sensíveis não necessários.

## R-004 — Seleção de opções ambíguas

- **Status**: `confirmado` pelo usuário.
- **Decisão**: não criar uma tool separada para escolher opções e não criar persistência especial. O agente lista opções com apenas os atributos necessários para distingui-las; o usuário escolhe na próxima mensagem. O workflow usa o contexto normal da conversa para resolver a referência e faz uma nova consulta autorizada antes de responder.
- **Alternativa rejeitada**: persistir um conjunto de candidatos/estado pendente em Mongo ou outro armazenamento. Isso adicionaria estrutura de memória e tratamento de ciclo de vida desnecessários para o comportamento solicitado.
- **Fallback**: se o contexto disponível não permitir determinar qual opção foi escolhida, pedir ao usuário para identificar o produto novamente; não escolher por conta própria.
- **Segurança**: a nova consulta reaplica email, role e escopo de loja derivados no servidor. Nenhum índice ou ID fornecido pelo cliente é autorização; nunca retornar dado apenas porque o modelo selecionou um candidato anterior.
- **Consequência**: testar resposta com opções distinguíveis, escolha clara na mensagem seguinte, referência ambígua/ausência de contexto e reconsulta respeitando escopo. Não exigir sobrevivência de seleção após reinício do processo.

## R-005 — Capacidades e dependências existentes

- **Status**: `implementado` para estrutura atual após integrar `002-autenticacao-api-ia` e `guardrail-semantic` em `product_workflow`; a feature ainda não implementada.
- `AGENTS.md` confirma que a API ativa atualmente apenas FAQ; `product_workflow` tem tipo de rota, mas não card/executor/tool registrados.
- `AuthenticatedPrincipal` expõe `email` e `role_id`; `/conversations/{conversation_id}/messages` autentica o Bearer JWE e atualmente passa somente email pelo controller/service ao `GraphState`. A feature deve propagar também o role ID autenticado; não aceitar role no body.
- `AuthenticatedPrincipal` não traz lojas. `user_store` precisa ser consultado no servidor, associado a `user_account.id` encontrado pelo email, e filtrado por vínculo ativo.
- A pool PostgreSQL e a dependência `get_postgres_pool` já existem; `psycopg_pool` está resolvido no projeto. Não criar conexão/driver paralelo sem necessidade.
- O ADR de autenticação atualmente limita o lookup ao `user_account`; Product Workflow também necessita `SELECT` read-only sobre `user_store`, `store`, `suggestion`, `suggestion_log`, `product`, `category` e, se o campo validade depender de lote, `batch`. O ADR/contrato deve ser ampliado para exatamente o conjunto necessário, sem DML/DDL.
- `ConversationResponse` já contém `clarification_required`; seleção será feita por texto em mensagem normal, sem campo novo no request e sem contrato de seleção pendente.
- `GraphState` já possui `product_workflow` em `RouteName` e resultado, mas não traz `card_snapshot` nem role. Não será ampliado com estado persistido de candidatos para esta feature.
- `ConversationService` cria estado por requisição e usa `conversation_id` como `thread_id`; a solução usa apenas o contexto normal disponível e, quando insuficiente, pede identificação novamente. Não depende de continuidade de checkpoint.
- As dependências resolvidas em `uv.lock` são LangChain 1.3.14 e LangGraph 1.2.10. Planejar com APIs compatíveis com essas versões e testar contra o lockfile, sem depender de APIs de versões mais novas.

## R-007 — Acesso PostgreSQL do Product Workflow

- **Status**: acesso estritamente read-only a dados necessários `confirmado`; extensão das permissões documentais do ADR de autenticação necessária.
- **Conflito identificado**: o ADR atual descreve SELECT exclusivo em `user_account`; a feature aprovada precisa consultar relacionamentos de loja e dados de sugestão/card.
- **Decisão**: estender o conjunto mínimo de SELECT da mesma conexão/pool read-only somente às tabelas usadas pela query de card. Nenhum privilégio de escrita, schema, usuário adicional ou mudança ao SQL comercial está no escopo.
- **Consequência**: antes de ativar a tool, atualizar o ADR/contrato, verificar privilégios efetivos no ambiente e provar com teste que consultas funcionam e operações de escrita continuam negadas.

## R-006 — Tratamento de falhas e não encontrado

- **Status**: `confirmado` na spec.
- **Decisão**: “nenhum produto/sugestão encontrada” é resultado tipado de domínio que orienta resposta restritiva; falha/timeout de PostgreSQL é erro de dependência e não deve parecer ausência de produto.
- **Consequência**: separar estados, mensagens, evidências e testes; nenhum fallback de conhecimento geral sobre preço, estoque, quantidade ou validade.
