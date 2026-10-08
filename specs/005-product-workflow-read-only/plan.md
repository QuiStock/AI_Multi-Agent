# Implementation Plan: Product Workflow consultivo

**Branch**: `005-product-workflow-read-only` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

## Summary

Registrar o Product Workflow no runtime do grafo como capacidade consultiva,
com tools tipadas e read-only. A primeira entrega consulta diretamente o
PostgreSQL comercial para funcionários e gerentes, sempre usando o escopo
derivado da identidade autenticada. Os campos de `suggestion` e
`suggestion_triage` são projetados pelo repositório SQL parametrizado; a
implementação exclui `EXPIRED` via `suggestion_log`, mas não retorna
`suggestion_decision` nem o histórico de `suggestion_log`.

## Technical Context

**Language/Version**: Python 3.14, FastAPI, LangGraph, Pydantic 2.x.

**Storage**: PostgreSQL comercial é consultado diretamente pela FastAPI com
credencial somente leitura. Spring permanece proprietária das escritas e dos
CRUDs comerciais.

**Identity**: o principal autenticado fornece email e role; o escopo de loja é
derivado no servidor. Funcionários e gerentes são aceitos; regional manager
permanece bloqueado pela autenticação atual.

**Evidence**: cada afirmação factual precisa apontar para `evidence_id` e
`source_id` estáveis, derivados da linha original lida no PostgreSQL.

**Testing**: unitário do repositório SQL, integração PostgreSQL, adapter do
grafo e casos negativos de isolamento/mutação/injeção.

## Constitution Check

- **Spec-first**: PASS — escopo, atores, opção B e limites estão registrados em
  `spec.md`.
- **Ownership**: PASS — a FastAPI só lê as tabelas comerciais com credencial
  read-only; a decisão e o impacto estão registrados no ADR.
- **Segurança**: PASS — email, papel e lojas vêm do principal/contexto do
  servidor; filtros do modelo não ampliam o escopo.
- **Groundedness**: PASS — o resultado não é sucesso sem fonte original e IDs
  de evidência.
- **Não mutação**: PASS — o repositório expõe apenas operações de leitura e
  não possui conexão ou método de escrita.

## Design

```text
GraphState.request
  -> ProductWorkflowExecutor
  -> PostgresProductWorkflowRepository
  -> PostgreSQL (SELECT parametrizado + escopo autenticado)
  -> typed read models
  -> evidence projection
  -> GraphState.agent_results.product_workflow + evidences
  -> Compiler -> Judge -> Output Guardrail
```

### Componentes

- `src/agents/product_workflow/models.py`: contexto, candidatos, card, triagem
  e envelope de leitura.
- `src/agents/product_workflow/repository.py`: repository direto, queries
  parametrizadas, escopo, busca por produto e detalhe role-projected.
- `src/agents/product_workflow/tools/`: exatamente duas tools para buscar
  candidatos e retornar o detalhe selecionado.
- `src/agents/product_workflow/card.py`: AgentCard, políticas e intents.
- `src/agents/product_workflow/executor.py`: execução controlada sem mutação.
- `src/graphs/adapters.py`: adaptação do resultado para `GraphState`.
- `src/api/dependencies.py`: wiring da capacidade com o pool PostgreSQL da
  aplicação.

## Rollout

1. Implementar modelos, repositório PostgreSQL, card, tools, executor e testes.
2. Registrar a capacidade no registry e no grafo usando o pool PostgreSQL
   existente.
3. Validar isolamento, evidências, ausência de mutações e falhas controladas.
4. Executar integração contra a massa PostgreSQL e validar os grants efetivos.

## Quality gates

```text
python -m pytest tests/test_product_workflow*.py tests/test_graph_adapters.py
ruff check .
ruff format --check .
mypy .
```

Não considerar o Product Workflow comercialmente pronto enquanto a integração
PostgreSQL, os grants de leitura e a evidência de isolamento não forem
entregues.
