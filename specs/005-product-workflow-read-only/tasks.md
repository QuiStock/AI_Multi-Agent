# Tasks: Product Workflow consultivo

**Input**: [spec.md](spec.md), [plan.md](plan.md)

## Phase 1: contrato interno e modelos

- [x] T001 [P] Criar modelos Pydantic read-only para contexto, candidatos,
  card, triagem, evidência e resultado em
  `src/agents/product_workflow/models.py`.
- [x] T002 [P] Criar o repositório PostgreSQL read-only para busca por produto,
  detalhe role-projected, exclusão de expiradas e seleção determinística em
  `src/agents/product_workflow/repository.py`.
- [x] T003 Registrar no ADR a decisão de acesso direto da FastAPI ao PostgreSQL,
  incluindo credencial, tabelas, escopo, timeout, auditoria e ausência de
  escrita.

## Phase 2: capacidade do agente

- [x] T004 Criar exatamente as tools tipadas de busca por produto e detalhe,
  sem SQL livre ou métodos de escrita.
- [x] T005 Criar `PRODUCT_WORKFLOW_CARD` e prompt consultivo com evidência
  obrigatória.
- [x] T006 Criar executor e adapter do grafo, propagando resultado e evidências
  para `GraphState`.
- [x] T007 Registrar card, repositório e capacidade no registry/dependencies,
  usando o pool PostgreSQL da aplicação.

## Phase 3: validação

- [x] T008 [P] Testar seleção da sugestão ativa mais recente e exclusão de
  sugestões rejeitadas/substituídas.
- [x] T009 [P] Testar queries parametrizadas, escopo por usuário/loja, limite
  de linhas e ausência de comandos de escrita no repositório PostgreSQL.
- [ ] T010 [P] Testar isolamento por funcionário/gerente, tentativa de trocar
  `store_id`, prompt injection e ausência de método mutável.
- [ ] T011 [P] Testar exclusão de `MONITOR` e `EXPIRED`, timeout,
  indisponibilidade e schema inválido.
- [ ] T012 Testar integração do Product Workflow no grafo e groundedness no
  judge.
- [ ] T013 Atualizar `AGENTS.md`, quickstart e evidências da feature após a
  integração PostgreSQL e os grants efetivos serem validados.

## Bloqueio explícito

T010 a T013 dependem da execução contra uma massa PostgreSQL real e da
validação dos grants efetivos. Os testes unitários do repositório não devem ser
apresentados como evidência de segurança de produção.
