# Tasks: Product Workflow consultivo para sugestões de produto

**Input**: Design artifacts in `specs/004-product-workflow/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/product-card-tool.md`, `quickstart.md`  
**Tests**: Incluídos conforme a Constituição e o `quickstart.md`; para cada fatia, escrevê-los antes da implementação.

## Phase 1: Setup

O projeto Python/FastAPI, pytest, LangGraph e contratos `ToolResult` já existem. Não há inicialização de projeto nem nova dependência de runtime prevista nesta fase.

## Phase 2: Foundational

**Purpose**: disponibilizar ao grafo o contexto autenticado e registrar a ampliação mínima, somente leitura, do acesso PostgreSQL necessário ao agente.

- [X] T001 [P] Testar propagação de `role_id` autenticado da rota para o estado do grafo (FR-006) em `tests/test_conversation_api.py` e `tests/test_graph_adapters.py`.
- [X] T002 Propagar `role_id` do `AuthenticatedPrincipal` junto ao email (FR-006, FR-007, FR-008) por `src/api/routes/conversation.py`, `src/api/controllers/conversation_controller.py`, `src/api/services/conversation_service.py` e `src/graphs/state.py`; manter a identidade exclusivamente derivada da autenticação.
- [X] T003 Documentar no contrato da feature e em `specs/002-autenticacao-api-ia/adr-001-ownership-postgres.md` o privilégio mínimo `SELECT` necessário para `user_account`, `user_store`, `suggestion`, `suggestion_log`, `product`, `category` e `batch`; `store` não é necessário porque o escopo usa o vínculo ativo em `user_store`. Não adicionar DDL ou privilégios de escrita. Registrar validação dos grants efetivos como requisito de implantação.

**Checkpoint**: identidade/email/role estão disponíveis ao grafo; tabelas autorizadas e limites read-only estão documentados antes da tool comercial.

## Phase 3: User Story 1 — Entender o card aberto (Priority: P1) 🎯 MVP

**Goal**: responder sobre o produto do card usando o snapshot recebido como evidência, sem consulta comercial.

**Independent Test**: POST com snapshot válido sobre o mesmo produto retorna resposta baseada no snapshot, registra proveniência cliente e não chama a tool/PostgreSQL.

### Tests for User Story 1

- [X] T004 [P] [US1] Testar validação do campo opcional de snapshot no request, incluindo estrutura válida e campos extras inválidos (FR-001), em `tests/test_conversation_api.py`.
- [X] T005 [P] [US1] Testar que snapshot válido gera evidência `client_card_snapshot` e não invoca lookup em `tests/test_product_card_repository.py`.
- [X] T006 [P] [US1] Testar que o juiz preserva a proveniência do snapshot cliente em `tests/test_judge_executor.py`.

### Implementation for User Story 1

- [X] T007 [US1] Definir schema tipado do snapshot/card com apenas os campos aceitos do contrato (FR-001) em `src/agents/product_workflow/schemas.py` e adicioná-lo como campo opcional em `src/api/schemas/conversation.py`.
- [X] T008 [US1] Transportar o snapshot do request até o grafo e declarar seu tipo de evidência (FR-001, FR-013) em `src/api/services/conversation_service.py` e `src/graphs/state.py`; atualizar os adapters em `src/graphs/adapters.py` para preservar fonte e conteúdo.
- [X] T009 [US1] Criar AgentCard, prompt e executor Product Workflow que priorizam snapshot para o mesmo produto, limitam afirmações às evidências e declaram ausência de justificativa não incluída (FR-002, FR-014, FR-015) em `src/agents/product_workflow/card.py`, `src/agents/product_workflow/product_workflow_prompt.py` e `src/agents/product_workflow/executor.py`.
- [X] T010 [US1] Integrar a resposta do Product Workflow à projeção de evidências consumida por compiler e judge sem permitir que o judge trate a origem cliente como consulta verificada (FR-013, FR-014), em `src/graphs/adapters.py`, `src/graphs/state.py` e `src/agents/judge/judge_prompt.py`.

**Checkpoint**: US1 funciona isoladamente com snapshot e zero acesso comercial.

## Phase 4: User Story 2 — Consultar outro produto ou iniciar sem card (Priority: P1)

**Goal**: procurar e explicar o card de outro produto sob o escopo atual do usuário, exibindo opções quando a consulta for ambígua.

**Independent Test**: pergunta sobre produto diferente/sem snapshot executa query parametrizada e read-only com email, role e loja derivados no servidor; exclui eventos `EXPIRED`; escolha clara na mensagem seguinte provoca nova busca autorizada.

### Tests for User Story 2

- [X] T011 [P] [US2] Testar filtros por funcionário/gerente, rejeição de roles fora de `2`/`3`, loja ativa e exclusão por `EXPIRED` em `tests/test_product_card_repository.py` e `tests/integration/test_product_card_postgres.py`.
- [X] T012 [US2] Testar query parametrizada, timeout e argumentos permitidos da tool em `tests/test_product_card_repository.py`.
- [X] T013 [P] [US2] Testar resposta única, ambiguidade e exposição mínima de campos em `tests/test_product_card_repository.py`.
- [X] T014 [P] [US2] Criar teste PostgreSQL descartável com filtros role/store, exclusão `EXPIRED`, batch e rejeição de escrita em `tests/integration/test_product_card_postgres.py`; execução local foi pulada por falta de Docker.

### Implementation for User Story 2

- [X] T015 [US2] Mapear os campos do card ao SQL e documentar joins mínimos, incluindo `batch` para validade física mostrada no card.
- [X] T016 [US2] Implementar query fixa parametrizada, loja ativa, limite e timeout usando pool existente em `src/agents/product_workflow/tools/product_card_repository.py`.
- [X] T017 [US2] Implementar schemas e tool usando `ToolResult` existente e outcomes `found`, `ambiguous` e `not_found`.
- [X] T018 [US2] Adaptar executor/prompt para priorizar snapshot, pesquisar outros produtos e expor somente campos mínimos na ambiguidade; reconsulta posterior usa contexto normal autenticado.
- [X] T019 [US2] Registrar card/executor e ativar rota; tool é injetada por requisição com pool/principal para evitar guardar identidade em registry global.

**Checkpoint**: consultas de outros produtos respeitam autorização, card, expiração e desambiguação; identidade ou loja jamais vêm do modelo/cliente.

## Phase 5: User Story 3 — Receber resposta segura em busca vazia ou indisponível (Priority: P1)

**Goal**: comunicar “não encontrado” de forma diferente de falha/timeout do banco e impedir respostas factuais sem evidência.

**Independent Test**: fixtures sem resultado e de falha PostgreSQL produzem estados/respostas distintos, ambos sem inventar dados; juiz só aprova afirmações cobertas pelo snapshot ou lookup.

### Tests for User Story 3

- [X] T020 [P] [US3] Testar resultado vazio versus dependência/timeout em `tests/test_product_card_repository.py`.
- [X] T021 [P] [US3] Testar rejeição/preservação de `insufficient_evidence` pelo juiz e resposta bloqueada do compiler quando não há resultados/evidências em `tests/test_judge_executor.py` e `tests/test_compiler.py`.
- [X] T022 [P] [US3] Testar fallback seguro e status terminal da rota Product Workflow em `tests/test_product_workflow_graph.py`.

### Implementation for User Story 3

- [X] T023 [US3] Mapear resultados vazios para `not_found` e falhas/timeout para categorias distintas sem dados no erro.
- [X] T024 [US3] Implementar respostas restritivas para ausência, indisponibilidade e seleção incerta.
- [X] T025 [US3] Integrar falhas em rota terminal e evidências ao compiler/judge.

**Checkpoint**: vazio, falha técnica e resposta fundamentada têm resultados observavelmente distintos.

## Final Phase: Polish & Cross-Cutting Concerns

- [X] T026 [P] Atualizar `AGENTS.md` com estado, card, tool, evidências e limites read-only.
- [X] T027 [P] Revisar logs e mensagens para não expor JWT, chave, email ou SQL sensível.
- [X] T028 Executar comandos e cenários do `specs/004-product-workflow/quickstart.md`, corrigir falhas e registrar evidências por RF/SC em `specs/004-product-workflow/`; integração PostgreSQL ficou documentada como skip por falta de Docker.
- [ ] T029 Executar suíte completa de validação documentada em `AGENTS.md` e integrar resultados unitários, API e PostgreSQL antes de considerar a feature concluída.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup**: nenhuma inicialização necessária; o repositório e dependências atuais já existem.
- **Foundational**: bloqueia as user stories porque role ainda não chega ao GraphState e os privilégios PostgreSQL precisam ser delimitados.
- **US1**: depende da fase Foundational; entrega o MVP de consulta ao card recebido sem SQL.
- **US2**: depende da US1 para reutilizar o schema do card, evidências e executor; adiciona a tool comercial.
- **US3**: depende de US2 para diferenciar os estados de resultado da tool e integrar falhas na rota.
- **Polish**: depende de todas as histórias.

### User Story Dependencies

- **US1 (P1)**: após Foundational; independente de lookup PostgreSQL.
- **US2 (P1)**: após US1; depende do contrato e da trilha de evidências de card.
- **US3 (P1)**: após US2; precisa dos resultados `not_found` e dependência definidos pela tool.

### Parallel Opportunities

- T001 pode ser feito em paralelo com T003; T002 depende de T001.
- Em US1, T004–T006 são testes em arquivos distintos; implementação T007–T010 segue o encadeamento schema → estado/adapters → executor → integração/judge.
- Em US2, T011, T013 e T014 podem ser escritos em paralelo; T012 deve ser serializado com T011 pois ambos alteram `tests/test_product_card_repository.py`. Depois, T015 mapeia o contrato e T016–T019 seguem repositório → tool → executor → wiring.
- Em US3, T020–T022 são testes paralelizáveis; T023–T025 seguem tool → executor → grafo.
- A ordem serial US1 → US2 → US3 evita conflitos no estado compartilhado, dependências ocultas e testes que assumam capacidades ainda não registradas.

### Parallel Example: US2 tests

```text
T011: filtros role/store/EXPIRED em tests/test_product_card_repository.py
T012: parametrização, limite e timeout em tests/test_product_card_repository.py (serializar alterações no mesmo arquivo)
T013: desambiguação em tests/test_product_workflow_executor.py
T014: integração em tests/integration/test_product_card_postgres.py
```

T011 e T012 editam o mesmo arquivo de teste e, portanto, devem ser serializados se executados por pessoas/agentes diferentes.

## Implementation Strategy

1. Completar Foundational e executar os testes de propagação de role.
2. Entregar US1 como primeiro MVP: card do app, sem consulta SQL.
3. Entregar US2 após comprovar grants read-only e mapear o contrato visual do card.
4. Entregar US3 e validar falhas, respostas restritivas e juiz.
5. Executar Polish e qualidade integral; não considerar consulta comercial pronta antes de comprovar os grants efetivos no ambiente de integração.
