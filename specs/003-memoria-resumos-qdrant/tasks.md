# Tasks: Persistência de turnos e resumos no Qdrant

**Input**: Design documents from `specs/003-memoria-resumos-qdrant/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/memory-persistence.md`, `quickstart.md`

**Tests**: Incluídos porque a constituição do serviço exige testes proporcionais, contrato verificável e evidências para alterações de persistência e memória.

**Organization**: As tarefas executáveis são agrupadas por história de usuário e dependências. Decisões de contrato e compatibilidade de versão do Qdrant foram registradas; a existência do índice de payload será validada durante a implementação.

## Phase 1: Setup e decisões de contrato

**Purpose**: Fechar pré-condições técnicas sem iniciar mudanças de schema com decisões abertas.

- [x] T001 [P] Registrar `messages` como nome físico do array (correspondente a `mensagens` no exemplo), além da preservação dos campos atuais de data/título e `_id`, sem `session_id` redundante, em `specs/003-memoria-resumos-qdrant/contracts/memory-persistence.md`.
- [x] T002 [P] Registrar que o Qdrant Cloud `Interdisciplinar` v1.19.1 suporta a ordenação de payload requerida; versões gerenciadas de MongoDB Atlas/Redis não são bloqueadoras sem dependência específica. Verificar/criar o índice de `updated_at` no trabalho de implementação T022 em `specs/003-memoria-resumos-qdrant/research.md`.

## Phase 2: Foundational — contrato de progresso e exclusão

**Purpose**: Definir marcadores e coordenação cross-store antes de implementar worker, reconciliação ou provisionamento das novas coleções.

- [x] T003 Atualizar o contrato de persistência em `specs/003-memoria-resumos-qdrant/contracts/memory-persistence.md` com watermark `message_id` ordenado pelo array canônico, versão não regressiva e revalidação imediatamente antes de gravar no Qdrant.
- [x] T004 Atualizar o contrato de persistência em `specs/003-memoria-resumos-qdrant/contracts/memory-persistence.md` com tombstone durável, estado `deleting`, coordenação por conversa e revalidação que impede job de recriar o ponto após exclusão.

**Checkpoint**: T001–T004 registrados, revisados e aprovados. Qdrant Cloud v1.19.1 suporta `order_by`; T022 deve verificar/criar o índice `updated_at` antes de ativar o fallback. Versões Atlas/Redis só precisam ser confirmadas se a implementação depender de uma funcionalidade específica delas.

## Phase 3: User Story 1 — Retomar conversa pelo histórico durável (Priority: P1)

**Goal**: Manter um documento MongoDB por conversa, mensagens em ordem no array acordado e retomada independente do resumo.

**Independent Test**: Criar uma conversa, acrescentar mensagens user/assistant (incluindo retry duplicado), encerrar e retomar; verificar um único documento, array em ordem, ausência de campos de resumo no estado final e isolamento por proprietário.

### Tests for User Story 1

- [x] T005 [P] [US1] Adicionar testes de integração para um documento por conversa, ordem das mensagens e ausência de `summary`, `summary_version` e `summarized_through_message_id` em `tests/integration/test_memory_mongo_repository.py`.
- [x] T006 [P] [US1] Adicionar testes de append duplicado por `message_id`, preservação da ordem do array e montagem de turnos user/assistant em `tests/test_memory_message_service.py`.
- [x] T007 [P] [US1] Adicionar testes de regressão de encerramento, retomada e isolamento do histórico sem depender de resumo Mongo em `tests/test_graph_memory_persistence.py`.

### Implementation for User Story 1

- [x] T008 [US1] Remover campos e modelos de resumo do documento de conversa, preservando `StoredMessage`, owner, status, timestamps e título em `src/memory/contracts.py`.
- [x] T009 [US1] Ajustar criação/append/listagem/retomada no repositório para manter um documento por conversa com array ordenado de mensagens e sem campos de resumo em `src/memory/mongo_repository.py`.
- [x] T010 [US1] Ajustar o serviço de mensagens para continuar persistindo mensagens finais idempotentes e compatíveis com o contrato físico confirmado em `src/memory/message_service.py`.
- [ ] T011 [US1] Executar e corrigir os testes da US1, incluindo `tests/integration/test_memory_mongo_repository.py`, `tests/test_memory_message_service.py` e `tests/test_graph_memory_persistence.py`.

## Phase 4: User Story 2 — Manter e recuperar resumo somente no Qdrant (Priority: P1)

**Goal**: Atualizar resumo em segundo plano, recuperar texto do Qdrant, manter busca/fallback coerentes e remover a duplicação no Mongo.

**Independent Test**: Encerrar conversa, processar/reprocessar o job e verificar que o Qdrant contém um único ponto atualizado até a última mensagem, o Mongo não contém texto/marcador de resumo e buscas semânticas/fallback não retornam dados de outro usuário.

### Tests for User Story 2

- [x] T012 [P] [US2] Adicionar testes para leitura, upsert idempotente, watermark e exclusão do ponto estável por conversa em `tests/test_qdrant_summary_indexer.py`.
- [ ] T013 [P] [US2] Adicionar testes do worker para reivindicação/lease, resumo incremental lido do Qdrant, falha após upsert antes de ack, concorrência e job que se torna obsoleto em `tests/test_summary_job_worker.py`. **Parcial**: ack/retry, bloqueio por lease, job obsoleto e operação de exclusão foram cobertos; falta teste cross-store com exclusão concorrente real.
- [x] T014 [P] [US2] Adicionar testes para candidatos semânticos e fallback recente usando texto Qdrant com validação Mongo somente de owner/status em `tests/test_memory_summary_context.py`.
- [x] T015 [P] [US2] Adicionar testes de deduplicação por `(conversation_id, closure_key)`, backoff crescente limitado, estado terminal observável e reprocessamento explícito em `tests/test_summary_jobs.py`.
- [x] T016 [P] [US2] Criar testes unitários do reconciliador para ponto ausente e ponto órfão em `tests/test_summary_reconciler.py`; a validação de watermark atrasado em serviço real permanece parte do cutover.

### Implementation for User Story 2

- [x] T017 [US2] Atualizar o contrato do ponto de resumo para incluir watermark de mensagem e progresso versionado, sem copiar esses dados para o documento da conversa, em `src/memory/contracts.py`.
- [ ] T018 [US2] Implementar leitura por ID determinístico, upsert com watermark e exclusão idempotente do resumo no Qdrant em `src/memory/qdrant_summary_indexer.py`. **Parcial**: operações, guarda contra regressão e listagem para reconciliação implementadas; falta comprovar concorrência e exclusão nos testes cross-store.
- [ ] T019 [US2] Adaptar o worker para carregar resumo anterior/progresso do Qdrant, resumir apenas mensagens posteriores ao watermark e concluir job somente após confirmar o upsert em `src/memory/worker/summarizer_end_conversation.py`. **Parcial**: rota/API integrada ao scheduler e processo separado do worker; falta validar ponta a ponta nos serviços alvo e cobrir concorrência com exclusão.
- [x] T020 [US2] Alterar geração de título para usar o resumo apenas em memória do worker e gravar somente o título no documento Mongo em `src/memory/worker/summarizer_end_conversation.py`.
- [x] T021 [US2] Alterar validação de candidatos para consultar Mongo apenas por owner/status e devolver o texto obtido do Qdrant em `src/memory/service.py` e `src/memory/mongo_repository.py`.
- [x] T022 [US2] Migrar o fallback de resumos recentes para filtro por usuário/status e ordenação `updated_at` no Qdrant com índice de payload verificado em `src/memory/service.py` e `src/memory/qdrant_summary_indexer.py`.
- [ ] T023 [US2] Implementar `closure_key` estável no scheduler interno, contrato/índices do job Mongo, relay/outbox Redis Streams, consumer group, leases, backoff limitado, operação de exclusão e reprocessamento de falha terminal sem persistir conteúdo de resumo em `src/memory/summary_scheduler.py`, `src/memory/summary_job_repository.py`, `src/memory/summary_lock_repository.py`, `src/memory/summary_queue.py` e `src/memory/worker/summary_job_worker.py`. **Parcial**: runtime local e processo separado implementados; falta validar implantação nos serviços alvo e concorrência cross-store.
- [x] T024 [US2] Implementar reconciliador retomável que compara últimas mensagens Mongo e watermark Qdrant, reenfileira ponto ausente/atrasado e remove ponto órfão em `src/memory/summary_reconciler.py`; o worker executa o ciclo periódico e `scripts/reconcile_memory.py` fornece o comando one-shot.
- [x] T025 [US2] Implementar exclusão idempotente com estado transitório/job durável, coordenação com worker e limpeza do ponto Qdrant e documento Mongo em `src/memory/mongo_repository.py`, `src/memory/summary_job_repository.py`, `src/memory/summary_scheduler.py`, `src/memory/conversation_cleanup.py` e `src/memory/worker/summary_job_worker.py`.
- [x] T026 [US2] Provisionar e validar coleções MongoDB/Qdrant novas e vazias, com email como identidade e sem importar histórico, em `scripts/provision_memory_collections.py`; a execução contra ambiente alvo permanece pendente.
- [ ] T027 [US2] Adicionar testes de integração do cutover para coleções vazias e da exclusão cross-store, incluindo interrupções/retries, em `tests/integration/test_memory_mongo_repository.py` e `tests/test_memory_collection_provisioning.py`.
- [ ] T028 [US2] Executar e corrigir a suíte de resumo/recuperação, incluindo `tests/test_summary_job_worker.py`, `tests/test_memory_summary_context.py`, `tests/test_qdrant_summary_indexer.py`, `tests/test_summary_reconciler.py` e testes de integração.

## Phase 5: Polish e evidências

**Purpose**: Atualizar guias operacionais e verificar os critérios completos sem expor conteúdo sensível.

- [ ] T029 [P] Atualizar o mapa de estado implementado e fluxo de memória em `AGENTS.md` após implementação, distinguindo capacidades existentes das novas.
- [ ] T030 Atualizar e executar o quickstart em `specs/003-memoria-resumos-qdrant/quickstart.md`, registrando comandos, resultados e limitações sem incluir texto de conversas/resumos.
- [ ] T031 [P] Registrar evidências dos critérios SC-001–SC-012 em `specs/003-memoria-resumos-qdrant/` e confirmar que as novas coleções usam email como identidade e não armazenam resumo no Mongo.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001–T002 concluídas; a compatibilidade do Qdrant está confirmada. O índice de payload continua uma validação de implementação em T022.
- **Foundational (Phase 2)**: T003–T004 concluídas com base no contrato de mensagens aprovado; bloqueiam worker, reconciliação, provisionamento das coleções novas e exclusão até a revisão do usuário (agora aprovada).
- **User Story 1 (Phase 3)**: depende do checkpoint fundacional; entrega histórico conversacional documentado e retomável.
- **User Story 2 (Phase 4)**: depende de US1 para usar o contrato final de conversa/mensagens; seus testes iniciais podem ser preparados após T003–T004.
- **Polish (Phase 5)**: depende das duas histórias e da validação das novas coleções vazias.

### User Story Dependencies

- **US1 (P1)**: começa após as decisões T001, T003 e T004; nenhuma dependência de resumo Qdrant para restaurar mensagens.
- **US2 (P1)**: depende do formato final de conversa da US1; antes de ativar a consulta de fallback ordenada por payload (T022), verificar/criar o índice no cluster. A história e o provisionamento das novas coleções devem estar completos antes do cutover.

### Parallel Opportunities

- A validação/criação do índice de payload em T022 pode ocorrer em paralelo com os testes que não dependam da consulta de fallback no ambiente-alvo.
- T005, T006 e T007 são testes em arquivos diferentes e podem ser preparados em paralelo após as decisões fundacionais.
- T012–T016 podem ser desenvolvidos em paralelo como testes separados; precisam da definição de watermark/coordenação T003–T004.
- T029 e T031 podem ocorrer em paralelo ao quickstart T030 quando a implementação e os critérios estiverem estáveis.

## Parallel Example: User Story 2

```text
Em paralelo, após T003–T004:
Task: T012 testes de ponto Qdrant em tests/test_qdrant_summary_indexer.py
Task: T014 testes de busca/fallback em tests/test_memory_summary_context.py
Task: T016 testes de reconciliação em tests/test_summary_reconciler.py

Depois dos testes:
T017–T018 -> T019–T022 -> T023–T027 -> T028
```

## Implementation Strategy

### MVP e cutover seguro

1. T001–T004 foram aprovadas; validar/criar o índice de `updated_at` em T022 antes de ativar fallback com `order_by`.
2. Implementar e validar US1 sem perder compatibilidade de leitura do histórico.
3. Implementar US2, worker, busca/fallback Qdrant, reconciliação e exclusão.
4. Provisionar e validar as novas coleções vazias, conferir índices e confirmar que nenhum dado antigo será importado.
5. **Não liberar o cutover parcial** que deixa o Mongo como fonte do resumo; os requisitos FR-002/FR-004 exigem concluir US2.
6. Validar os critérios SC-001–SC-012, atualizar evidências e só então marcar a feature implementada.

### Observações de execução

- Cada implementação de teste deve primeiro reproduzir o comportamento esperado e falhar no código antigo.
- A exclusão HTTP pública segue o contrato FR-WRK-009: Bearer JWE, sem email no
  body/query, resposta `202` e limpeza cross-store assíncrona.
- Erros/métricas podem registrar IDs técnicos e status, mas nunca texto de resumo, mensagem privada, prompt, segredo ou token.
