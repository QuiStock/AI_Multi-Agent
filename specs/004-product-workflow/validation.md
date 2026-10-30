# Evidências de validação — Product Workflow

**Data:** 2026-10-02  
**Branch:** `product_workflow`

## Verificações locais

- `pytest -p no:cacheprovider -o addopts='' -m 'not integration' -q`: **250 passed**, 34 testes de integração foram excluídos; restaram três avisos conhecidos de dependências/Qdrant local.
- `pytest -p no:cacheprovider -m integration tests/integration/test_product_card_postgres.py -q`: teste **skip**, pois não há daemon Docker Desktop disponível para iniciar PostgreSQL efêmero.
- Ruff `check` nos arquivos alterados: **passou**.
- Ruff `format --check` nos arquivos alterados: **passou**.
- `mypy src`: **passou**, 117 arquivos verificados.

## Pendências antes de considerar a consulta comercial pronta para produção

1. Executar `tests/integration/test_product_card_postgres.py` em CI/ambiente com Docker e confirmar que o papel PostgreSQL da API consegue ler apenas as tabelas autorizadas e não consegue escrever.
2. Validar com o contrato real do frontend a precedência `current_*` → `ml_*` e a validade visual, hoje mapeada para a menor `batch.expiration_date` de lotes ativos com saldo positivo. A validade da promoção permanece separada.
3. Comprovar os grants efetivos `SELECT` no PostgreSQL de integração; o código e o ADR não aplicam permissões.

O comando de lint do repositório inteiro encontrou diretórios `pytest-cache-files-*` com acesso negado no workspace e não pôde completar a varredura global. Os arquivos da feature e dependências diretamente alteradas passaram nas verificações direcionadas acima.
