---

description: "Tarefas para consolidar o planejamento do serviço de IA"

---

# Tasks: Consolidar o planejamento do serviço de IA

**Input**: Design documents from `specs/001-consolidar-planejamento-ia/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`,
`contracts/` e `quickstart.md`

**Tests**: Esta feature é documental. As tarefas de validação verificam
estrutura, rastreabilidade e evidências; testes de runtime serão executados
nas funcionalidades futuras correspondentes.

**Organization**: As tarefas seguem as histórias de usuário da especificação.

## Repository Path Convention

- Paths for this repository are relative to the `AI_Multi-Agent` root, such as
  `src/`, `tests/`, `docs/` and `specs/`.
- Paths in the other repository use the explicit prefix `Quistock:`, followed
  by a path relative to that repository root, such as `Quistock:docs/sdd/`.
- Do not use machine-specific absolute paths in this task list.

## Format

Cada tarefa usa o formato `- [ ] T### [P?] [Story?] descrição com caminho de arquivo`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirmar a estrutura da feature e preparar o inventário da
auditoria.

- [x] T001 [P] Confirmar a feature ativa e a presença de `.specify/feature.json`, `specs/001-consolidar-planejamento-ia/spec.md`, `specs/001-consolidar-planejamento-ia/plan.md`, `specs/001-consolidar-planejamento-ia/research.md`, `specs/001-consolidar-planejamento-ia/data-model.md`, `specs/001-consolidar-planejamento-ia/contracts/audit-inventory.md` e `specs/001-consolidar-planejamento-ia/quickstart.md`.
- [x] T002 Criar o esqueleto do inventário em `specs/001-consolidar-planejamento-ia/audit-inventory.md` com as colunas `item_id`, `title`, `status`, `current_state`, `target_state`, `source_refs`, `evidence_refs`, `impact` e `next_action`, conforme `specs/001-consolidar-planejamento-ia/contracts/audit-inventory.md`.
- [x] T003 Registrar no cabeçalho de `specs/001-consolidar-planejamento-ia/audit-inventory.md` o escopo dos dois repositórios, os cinco status permitidos e as exclusões de caches, ambientes virtuais, artefatos gerados e segredos.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Catalogar as fontes antes de classificar decisões, capacidades ou
divergências.

**⚠️ CRITICAL**: Nenhuma história de usuário pode ser concluída antes desta
fase, porque todas dependem de referências estáveis.

- [x] T004 Catalogar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` os artefatos relevantes deste repositório, incluindo `src/`, `tests/`, `docs/`, `.specify/`, `.agents/`, `AGENTS.md`, configurações e contratos.
- [x] T005 Catalogar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` os arquivos do Quistock que definem regras de negócio, requisitos acadêmicos, modelos de dados, scripts de integração ou contratos ligados ao serviço de IA; registrar cada caminho relativo com o prefixo `Quistock:` e justificar qualquer inclusão fora dessas categorias.
- [x] T006 Registrar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` as relações entre os dois repositórios, identificando dependências de regras de negócio, contratos, dados, memória e integrações.
- [x] T007 Verificar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` que nenhum caminho excluído ou segredo foi usado como fonte de decisão ou evidência.

**Checkpoint**: As fontes da auditoria estão catalogadas e o inventário pode
ser revisado sem depender de memória da conversa.

---

## Phase 3: User Story 1 - Entender o estado real do serviço de IA (Priority: P1) 🎯 MVP

**Goal**: Produzir uma visão verificável do que está implementado, planejado,
indefinido ou ausente.

**Independent Test**: Para cada área relevante, a equipe consegue localizar a
fonte, o estado atual, o estado-alvo, a classificação e as evidências no
inventário.

### Validation for User Story 1

- [x] T008 [US1] Identificar capacidades implementadas em `src/`, `tests/` e `Quistock:ai-service/`, registrando `current_state` e `evidence_refs` em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T009 [US1] Comparar o comportamento observado com `AGENTS.md`, `docs/`, `Quistock:docs/sdd/` e as demais fontes catalogadas, registrando `target_state` e limitações em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T010 [US1] Classificar cada item auditado em `specs/001-consolidar-planejamento-ia/audit-inventory.md` com exatamente um dos status definidos em `specs/001-consolidar-planejamento-ia/contracts/audit-inventory.md`.
- [x] T011 [US1] Adicionar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` as referências de código, teste, documento, execução ou demonstração que sustentam cada item `implementado`.
- [x] T012 [US1] Executar os cenários de validação de `specs/001-consolidar-planejamento-ia/quickstart.md` e registrar os resultados observados em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.

**Checkpoint**: A primeira auditoria apresenta estado atual, estado-alvo,
status e evidências para as áreas relevantes do serviço.

---

## Phase 4: User Story 2 - Decidir o que deve permanecer no planejamento (Priority: P1)

**Goal**: Tornar divergências e decisões pendentes explícitas antes da criação
de tarefas de implementação.

**Independent Test**: Cada item `aberto` ou `divergente` possui fontes,
impacto, decisão necessária e próxima ação registrada.

- [x] T013 [US2] Comparar fontes conflitantes em `AGENTS.md`, `src/`, `tests/` e nos caminhos concretos catalogados em T005, registrando cada conflito em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T014 [US2] Classificar como `divergente` os itens em que código e testes ou documentos apresentam comportamentos incompatíveis, preservando todas as fontes em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T015 [US2] Registrar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` as decisões necessárias, impactos, responsáveis pela próxima decisão e condições para retirar cada item de `aberto` ou `divergente`.
- [x] T016 [US2] Confirmar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` que decisões `confirmado` podem ter implementação pendente sem serem rebaixadas para `proposto` ou classificadas como `divergente`.
- [x] T017 [US2] Verificar cada item `aberto` em `specs/001-consolidar-planejamento-ia/audit-inventory.md`, registrar suas tarefas dependentes e confirmar que elas não podem começar até a decisão ser resolvida; documentar o resultado no próprio inventário.

**Checkpoint**: Nenhum conflito fica oculto e nenhuma decisão aberta gera
implementação arbitrária.

---

## Phase 5: User Story 3 - Planejar uma funcionalidade com rastreabilidade (Priority: P2)

**Goal**: Ligar requisitos, decisões, evidências e futuras funcionalidades aos
artefatos do Spec Kit.

**Independent Test**: A equipe consegue sair de um requisito ou item auditado e
chegar à especificação, plano, tarefa e evidência correspondente quando esses
artefatos existirem.

- [x] T018 [US3] Mapear `FR-001` a `FR-013` e `SC-001` a `SC-006` para itens, decisões e evidências em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T019 [US3] Registrar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` quais capacidades implementadas são relevantes para a rubrica acadêmica e quais exigem especificação retrospectiva completa.
- [x] T020 [US3] Registrar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` cada mudança ou funcionalidade futura identificada, com motivação, status, prioridade sugerida e slug provisório para uma futura pasta em `specs/`.
- [x] T021 [US3] Para cada funcionalidade futura explicitamente escolhida pela equipe como próximo ciclo, executar o fluxo `$speckit-specify` para criar sua pasta e `spec.md` sob `specs/`, depois registrar o caminho gerado em `feature_ref` no inventário; se nenhuma for escolhida nesta revisão, registrar essa condição em `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T022 [US3] Verificar em `specs/001-consolidar-planejamento-ia/spec.md`, `specs/001-consolidar-planejamento-ia/plan.md`, `specs/001-consolidar-planejamento-ia/tasks.md` e `specs/001-consolidar-planejamento-ia/audit-inventory.md` que cada requisito possui caminho de rastreabilidade ou justificativa explícita para estar aberto.

**Checkpoint**: Os resultados da auditoria conseguem orientar novas
especificações independentes sem duplicar decisões históricas.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validar a entrega documental e preparar a análise de consistência.

- [x] T023 Validar o checklist em `specs/001-consolidar-planejamento-ia/checklists/requirements.md` e registrar regressões ou itens pendentes no inventário.
- [x] T024 [P] Executar `git diff --check` e revisar os links dos artefatos em `specs/001-consolidar-planejamento-ia/plan.md`, `specs/001-consolidar-planejamento-ia/quickstart.md` e `specs/001-consolidar-planejamento-ia/audit-inventory.md`.
- [x] T025 Consolidar em `specs/001-consolidar-planejamento-ia/audit-inventory.md` o resumo de cobertura, lacunas, divergências e recomendações para as próximas features.
- [x] T026 Executar o `$speckit-analyze` sobre `specs/001-consolidar-planejamento-ia/spec.md`, `specs/001-consolidar-planejamento-ia/plan.md` e `specs/001-consolidar-planejamento-ia/tasks.md` antes de considerar a feature pronta para implementação.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Não depende de outras fases; prepara o inventário.
- **Foundational (Phase 2)**: Depende da Setup e bloqueia as histórias.
- **User Story 1 (Phase 3)**: Depende da Foundation e entrega o MVP da auditoria.
- **User Story 2 (Phase 4)**: Depende da User Story 1 porque exige comparar fontes catalogadas.
- **User Story 3 (Phase 5)**: Depende das User Stories 1 e 2 para não criar rastreabilidade sobre estados ainda indefinidos.
- **Polish (Phase 6)**: Depende das três histórias e prepara a análise final.

### User Story Dependencies

- **US1 (P1)**: Depois da Foundation; não depende de outra história.
- **US2 (P1)**: Depois da US1; usa o inventário e as evidências catalogadas.
- **US3 (P2)**: Depois da US1 e US2; usa classificações e decisões resolvidas.

### Parallel Opportunities

- T001 pode ser executada em paralelo com a revisão inicial dos documentos já existentes.
- T022 e T023 são sequenciais: ambas podem consultar/atualizar `audit-inventory.md` ao registrar lacunas.
- A coleta de evidências de código e a coleta de evidências documentais podem ser distribuídas entre integrantes, desde que a consolidação em `audit-inventory.md` seja sequencial.

## Parallel Example: User Story 1

```text
T008: coletar evidências do código e dos testes em `src/`, `tests/` e `Quistock:ai-service/`
T009: comparar documentação em `docs/` e `Quistock:docs/sdd/`
T010-T012: consolidar, classificar e validar o inventário em sequência
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Concluir Setup e Foundation.
2. Executar a auditoria do estado atual na US1.
3. Validar o inventário pelo quickstart.
4. Parar e revisar o inventário antes de resolver divergências ou criar novas features.

### Incremental Delivery

1. US1 entrega o inventário do estado atual.
2. US2 registra decisões, lacunas e divergências.
3. US3 transforma mudanças aprovadas em futuras especificações Spec Kit.
4. Polish executa o `speckit-analyze` e fecha a rastreabilidade.

## Notes

- As tarefas desta feature alteram apenas artefatos de planejamento, salvo a
  criação de novas especificações explicitamente aprovada em T020.
- Não criar tarefas de runtime para itens `aberto` ou `divergente`.
- Tarefas com `[P]` não podem editar o mesmo arquivo simultaneamente.
- O `$speckit-analyze` deve ser executado somente depois que este `tasks.md`
  estiver completo.
