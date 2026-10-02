# Quickstart: validar autenticação e identidade

## Pré-requisitos

- Python e dependências do projeto instalados pelo fluxo padrão do repositório.
- Docker ativo para executar o teste de integração PostgreSQL; o próprio teste cria a tabela e a role de somente leitura.
- Operador fornece `POSTGRES_DSN` e `JWE_PRIVATE_KEYS_JSON` no `.env`; a segunda variável é um JSON `kid` → chave privada PEM. Nunca incluir os valores reais no controle de versão.
- Configuração de teste JWE com `RSA-OAEP-256` e `A256GCM`; em teste de rotação, incluir chave anterior e nova e validar seleção via `kid`. MongoDB/Redis/Qdrant/provedores podem ser substituídos por doubles nos testes unitários.
- Nunca usar segredos reais em fixtures, exemplos ou logs.

## Validação automatizada

```powershell
uv run pytest
uv run pytest -m integration tests/integration/test_auth_postgres.py
uv run ruff check src tests
uv run mypy src
```

## Evidências desta implementação

- Suíte padrão: `236 passed, 33 deselected` (inclui testes unitários/contrato; testes marcados `integration` são excluídos pela configuração padrão).
- Autenticação e health: `26 passed` após a checagem adicional de rotação de chaves.
- Ruff e mypy: aprovados; `git diff --check` sem erros; `rg -n user_id src` sem ocorrências.
- O teste de integração PostgreSQL foi iniciado explicitamente, mas não pôde ser executado porque o Docker Engine não está disponível nesta máquina. T035 permanece pendente para um ambiente de integração com Docker/PostgreSQL.

## Cenários obrigatórios

1. JWE válido com email existente e papel permitido: operação usa o email do token e chega ao fluxo.
2. Ausente, malformado, não descriptografável ou sem claim email; e email não encontrado: `401`, sem grafo ou escrita. Token expirado não deve chegar à API; não há cenário de validação local de expiração.
3. `role_id = 1`: `403`, sem grafo ou escrita.
4. PostgreSQL indisponível/consulta falha: `500`, sem grafo ou escrita.
5. Requisição contendo `user_id` não altera principal; identidade dos dados vem exclusivamente do token.
6. Email A não lista, lê, retoma, encerra ou modifica conversa de email B; jobs e Qdrant também mantêm isolamento.
7. Health: cada dependência falha individualmente → HTTP `500`, `status: "error"` e check correspondente `"unavailable"`; todas disponíveis → HTTP `200`, `status: "ok"` e todos os checks `"ok"`; probes dos catálogos Gemini/Groq não disparam geração de texto.

O teste de integração cria uma base efêmera e verifica que a role de consulta consegue ler `email`/`role_id`, mas não consegue atualizar linhas nem executar DDL. A validação dos grants da credencial de implantação depende do PostgreSQL configurado pelo operador.
