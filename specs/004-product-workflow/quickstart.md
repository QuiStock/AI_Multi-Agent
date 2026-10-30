# Historical quickstart — superseded

Use `specs/005-product-workflow-read-only` for the active Product Workflow
contract. The active implementation exposes only
`get_suggestion_for_product` followed by `get_suggestion_detail`.

# Quickstart — Product Workflow Validation

Este roteiro será executável após a implementação das tarefas. Comandos seguem o contrato atual de validação em `AGENTS.md`.

## 1. Ambiente e validações estáticas

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

## 2. Testes focados

```powershell
uv run pytest tests/test_conversation_api.py
uv run pytest tests/test_product_workflow.py tests/test_product_workflow_repository.py
uv run pytest tests/test_product_workflow_graph.py
uv run pytest tests/test_judge_executor.py
```

Os testes da API validam o snapshot opcional e a propagação do cargo; os testes do repositório verificam query parametrizada, role/store, expiração, ambiguidades e falhas distintas.

## 3. Cenários de contrato e integração

Executar `uv run pytest -m integration tests/integration/test_product_workflow_postgres.py` com PostgreSQL descartável, nunca contra produção. Cobrir:

1. Pergunta sobre o mesmo card: usa snapshot, evidência marcada como origem cliente e zero chamadas SQL.
2. Produto diferente/sem snapshot: usa somente tool registrada e query parametrizada.
3. Visibilidade funcionário (`IN_EMPLOYEE_TRIAGE` e `available_for_triage`) e
   gerente (`SENT_TO_MANAGER`), com isolamento negativo entre lojas.
4. Sugestão relacionada a evento `EXPIRED` excluída; sugestão vigente retornada no contrato de card.
5. Zero resultados comunicado como não encontrado; timeout/indisponibilidade comunicado como falha segura distinta.
6. Nome ambíguo gera lista com nome/categoria/SKU somente e não produz resposta factual sobre item ainda não escolhido.
7. Opções ambíguas mostram somente os atributos necessários para distingui-las; escolha clara na mensagem seguinte provoca nova consulta sob o escopo autenticado atual.
8. Se não houver contexto suficiente para entender a escolha, o agente pede que o usuário identifique o produto novamente, sem selecionar um item por conta própria.
9. Compiler e judge preservam suporte e proveniência do snapshot/resultado SQL; alegação não coberta é bloqueada.

## 4. Suíte completa

```powershell
uv run pytest
uv run pytest -m integration
```

## 5. Evidências a registrar

Vincular resultados dos testes aos RF/CA em `tasks.md`. O contrato do frontend ainda precisa validar se a precedência SQL `current_*` → `ml_*` e os campos estruturados coincidem com o card exibido antes da implantação. Grants efetivos `SELECT` também precisam ser demonstrados em ambiente de integração.
