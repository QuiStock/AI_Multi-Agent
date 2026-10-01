# Tasks: Autenticação e identidade na API de IA

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/identity-and-health.md](contracts/identity-and-health.md), [quickstart.md](quickstart.md)

**Regra de bloqueio**: decisões criptográficas e de rotação estão registradas na spec; não alterar algoritmos nem política sem nova revisão. Valores reais e formato operacional do `.env` são fornecidos pelo operador e não devem ser criados/alterados nesta implementação. Tokens expirados são barrados antes da API e não são validados por ela.

## Phase 1: Setup e decisão de segurança

**Purpose**: preparar as dependências/configuração sem segredos, seguindo as decisões criptográficas aprovadas.

- [x] T001 Registrar política de rotação: `kid` protegido, convivência temporária da chave nova e anterior, retirada da anterior após a janela de encaminhamento e revogação imediata em comprometimento; documentado em `spec.md` e `research.md`. Valores/serialização de `.env` são responsabilidade do operador; versão de `jwcrypto` é fechada ao travar dependências em T003.
- [x] T002 [P] Adicionar os nomes/placeholders `JWE_PRIVATE_KEYS_JSON` e `POSTGRES_DSN` em `.env.example` e `src/config.py`; valores reais permanecem sob responsabilidade do operador
- [x] T003 Adicionar driver/pool PostgreSQL e biblioteca `jwcrypto`, travando dependências em `pyproject.toml` e `uv.lock` após validar compatibilidade com Python 3.14

## Phase 2: Foundational

**Purpose**: criar a fronteira de confiança, configuração dos serviços e erros comuns que bloqueiam as histórias.

- [x] T004 Criar tipos `AuthenticatedPrincipal` e erros internos de token/lookup em `src/auth/models.py` e `src/auth/errors.py`
- [x] T005 [P] Implementar consulta parametrizada de `email` e `role_id` em `user_account` com timeout e credencial somente leitura em `src/auth/account_repository.py`
- [x] T006 Implementar lifecycle/gestão do pool PostgreSQL, startup/shutdown e encerramento do pool em `src/auth/postgres.py` e `src/main.py`
- [x] T007 Registrar configurações de DSN, chave JWE e timeouts sem expor valores em `src/config.py`
- [x] T008 Mapear erros de autenticação para respostas genéricas seguras sem token, claim, chave ou SQL em `src/api/dependencies.py`

## Phase 3: User Story 1 — usuário autenticado acessa conversas (P1) 🎯 MVP

**Goal**: somente identidade JWE válida, existente no banco e autorizada atravessa a fronteira antes de controller/grafo.

**Independent Test**: testar token ausente/inválido, conta ausente, gerente regional, erro PostgreSQL e identidade válida; erros não iniciam grafo nem persistência.

### Tests

- [x] T009 [P] [US1] Criar testes de decrypt/claims JWE válidos e inválidos e ausência de email em `tests/test_auth_token.py`; não testar expiração, pois tokens expirados não chegam à API
- [x] T010 [P] [US1] Criar testes de lookup email encontrado/não encontrado, timeout e indisponibilidade em `tests/test_auth_repository.py`
- [x] T011 [P] [US1] Criar testes de contrato `401`, `403`, `500` e garantia de que o grafo não é chamado em falhas em `tests/test_auth_dependency.py`
- [x] T012 [P] [US1] Criar teste de integração read-only da consulta de identidade com PostgreSQL em `tests/integration/test_auth_postgres.py`

### Implementation

- [x] T013 [US1] Implementar validação/descriptografia JWE e extração estrita da claim `email` conforme decisão aprovada em `src/auth/token.py`
- [x] T014 [US1] Implementar serviço de autenticação que consulta conta, retorna `401` sem correspondência, `403` para `role_id = 1` e `500` para falha operacional em `src/auth/service.py`
- [x] T015 [US1] Disponibilizar dependência FastAPI que constrói `AuthenticatedPrincipal` antes dos controllers protegidos em `src/api/dependencies.py`
- [x] T016 [US1] Proteger rotas de conversa/mensagem, listagem e encerramento, deixando `/health` fora da dependência de usuário, em `src/api/routes/conversation.py`, `src/api/routes/conversation_list.py` e `src/api/routes/conversation_end.py`
- [x] T017 [US1] Registrar falhas de autenticação sem token, chave, email integral ou dados sensíveis em `src/observability/audit.py`

## Phase 4: User Story 2 — email confiável propagado às capacidades (P1)

**Goal**: retirar `user_id` como identidade do contrato público e usar o principal validado para autorização, grafo, Mongo, Qdrant e jobs.

**Independent Test**: chamar endpoints sem `user_id`; verificar persistência/consulta do email do JWE em todos os caminhos e isolamento entre dois emails, inclusive no worker.

### Tests

- [x] T018 [P] [US2] Atualizar testes de contrato de conversa para Bearer JWE, remoção de `user_id` e falha sem execução do grafo em `tests/test_conversation_api.py`
- [x] T019 [P] [US2] Atualizar testes de listagem/encerramento e isolamento entre emails em `tests/test_conversation_list_api.py` e `tests/test_conversation_end_api.py`
- [x] T020 [P] [US2] Substituir fixtures/campos de identidade por email nos testes de estado, grafo, adapters e guardrails em `tests/test_agent_graph.py`, `tests/test_graph_adapters.py`, `tests/test_graph_memory_persistence.py`, `tests/test_input_guardrail.py`, `tests/test_router_graph.py`, `tests/test_shared_state.py` e `tests/integration/test_judge_graph_integration.py`
- [x] T021 [P] [US2] Substituir fixtures/campos de identidade por email nos testes de contexto, Mongo, memória, Qdrant e busca semântica em `tests/test_enrich_context.py`, `tests/test_memory_message_service.py`, `tests/test_memory_summary_context.py`, `tests/test_memory_summary_repository.py`, `tests/test_qdrant_summary_indexer.py`, `tests/test_router_memory_tool.py` e `tests/integration/test_memory_mongo_repository.py`
- [x] T022 [P] [US2] Substituir fixtures/campos de identidade por email nos testes do sumarizador, worker e jobs em `tests/test_summarizer_end_conversation.py`, `tests/test_summary_job_worker.py` e `tests/test_summary_jobs.py`

### Implementation

- [x] T023 [US2] Remover `user_id` dos schemas/query públicos, obter principal autenticado nos controllers/dependencies/services e derivar ownership do email em `src/api/schemas/conversation.py`, `src/api/schemas/conversation_end.py`, `src/api/routes/conversation_list.py`, `src/api/controllers/conversation_controller.py`, `src/api/controllers/conversation_list_controller.py`, `src/api/controllers/conversation_end_controller.py`, `src/api/dependencies.py`, `src/api/services/conversation_service.py`, `src/api/services/conversation_list_service.py` e `src/api/services/conversation_end_service.py`
- [x] T024 [US2] Propagar `email` em estado, adaptadores do grafo, contexto do router e busca semântica em `src/graphs/state.py`, `src/graphs/adapters.py`, `src/agents/router/executor.py` e `src/agents/router/tools/search_conversation_summaries.py`
- [x] T025 [US2] Substituir identidade `user_id` por email em contratos, serviços e documentos Mongo, incluindo filtros de ownership em `src/memory/contracts.py`, `src/memory/enrich_context.py`, `src/memory/get_summary_context.py`, `src/memory/message_service.py`, `src/memory/mongo_repository.py` e `src/memory/service.py`
- [x] T026 [US2] Substituir identidade em payloads/filtros Qdrant e metadados/repositórios/agendamento de jobs em `src/memory/qdrant_summary_indexer.py`, `src/memory/summary_job_repository.py`, `src/memory/summary_jobs.py` e `src/memory/summary_scheduler.py`
- [x] T027 [US2] Propagar email pelo sumarizador e worker e validar proprietário de conversa/job antes de atualizar stores em `src/memory/worker/summarizer_end_conversation.py` e `src/memory/worker/summary_job_worker.py`
- [x] T028 [US2] Remover `user_id` de mensagens de erro públicas e do contrato OpenAPI, sem expor identidade em erro, em `src/api/errors.py` e `src/api/schemas/`

## Phase 5: User Story 3 — prontidão da API e dependências (P2)

**Goal**: `/health` informa readiness da API e de todos os stores/provedores exigidos sem autenticação de usuário ou geração de texto.

**Independent Test**: cada dependência indisponível isoladamente retorna `500`; todas disponíveis retornam `200`; probes têm timeout e não iniciam grafo/model generation.

### Tests

- [x] T029 [P] [US3] Cobrir HTTP `200` com todos os checks `ok`, HTTP `500` com check individual `unavailable`, timeout e ausência de geração de texto em `tests/test_health_api.py`

### Implementation

- [x] T030 [US3] Implementar probes com timeout para PostgreSQL, MongoDB, Redis, Qdrant, Gemini e Groq em `src/api/services/health_service.py`
- [x] T031 [US3] Atualizar `/health` para retornar `200` somente com todas as dependências disponíveis e `500` em qualquer falha, sem detalhes sensíveis, em `src/api/routes/health.py`

## Phase 6: Polish e cross-cutting

- [x] T032 [P] Atualizar instruções e planejamentos ativos para usar email como identidade em `AGENTS.md`, `docs/planejamento-memory.md` e `docs/planejamento-multiagente-fastapi.md`; preservar menções a `user_id` apenas em inventários históricos e critérios que verificam sua remoção
- [x] T033 Validar casos ponta a ponta e atualizar comandos/saídas esperadas em `specs/002-autenticacao-api-ia/quickstart.md`
- [x] T034 Executar pytest, lint, type-check e `git diff --check`; confirmar que nenhum código usa `user_id` como identidade em request, estado, persistência ou job; registrar resultados vinculados a FR/SC em `specs/002-autenticacao-api-ia/quickstart.md`
- [ ] T035 Confirmar em ambiente de integração a credencial PostgreSQL sem escrita/DDL e documentar grants efetivos em `specs/002-autenticacao-api-ia/adr-001-ownership-postgres.md` (pendente: executar contra o PostgreSQL do ambiente de integração)

## Dependencies & Execution Order

### Phase Dependencies

- Setup: T001 (decisão documental) concluída; T002/T003 podem seguir conforme a configuração fornecida pelo operador e a compatibilidade da dependência.
- Foundational: depende do setup; T004–T008 habilitam as histórias.
- US1: depende de foundation e das decisões de segurança registradas na T001.
- US2: depende de US1 para obter principal confiável; a suíte é deliberadamente ampla porque o email deve atravessar todo o fluxo.
- US3: depende das interfaces de readiness/configuração fundacional; pode ser implementada em paralelo com US2 após foundation.
- Polish: após as três histórias.

### Parallel Opportunities

- T002 e preparação de testes T009–T012 podem avançar em paralelo; T003 deve estar fechado antes de implementar o adaptador.
- Em US2, grupos T020 (grafo/Mongo) e T021 (jobs/Qdrant) podem ser executados em paralelo por arquivos distintos; integração final depende de T023/T024.
- US3 (T029–T031) pode avançar em paralelo com US2 após os contratos/probes e config serem acordados.

## Implementation Strategy

1. Aplicar as decisões JWE/rotação aprovadas e usar configuração de ambiente fornecida pelo operador; não versionar segredos.
2. Construir e validar US1: credencial + conta + papel, antes do grafo.
3. Entregar US2 como mudança atômica de identidade email em request, graph, Mongo, Qdrant e jobs; sem migração de dados antigos.
4. Entregar readiness US3 e validar falhas individuais.
5. Rodar quickstart e quality gates; anexar evidências aos requisitos FR/SC.

## Requirement Traceability

- FR-001–FR-007, FR-010, FR-012–FR-014 → US1 (T009–T017).
- FR-002–FR-004, FR-008–FR-009, FR-011, FR-015–FR-016, FR-018 → US2 (T018–T028, T035).
- FR-017, SC-008, SC-010 → US3 (T029–T031).
- SC-004–SC-007, SC-009, SC-011 → US1/US2/US3 e validação final (T017, T021–T035).
