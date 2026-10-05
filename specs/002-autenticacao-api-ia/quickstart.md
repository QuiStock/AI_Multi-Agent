# Quickstart: autenticação HS256

## Configuração

- Configurar `JWT_SECRET` como segredo aleatório forte no ambiente da API de IA e do emissor confiável. Não incluir segredo real no Git nem no cliente.
- Configurar `POSTGRES_DSN` com usuário exclusivo somente de leitura para `user_account.email` e `user_account.role_id`.
- A API valida assinatura HS256 e claim `email`; não valida `exp` por decisão de escopo. O emissor/encaminhador só deve encaminhar tokens válidos.

## Casos de aceite

1. JWT assinado com o segredo compartilhado, email existente e `role_id` permitido: a rota usa a identidade consultada e prossegue.
2. Bearer ausente, JWT malformado, assinatura inválida, algoritmo diferente, email ausente/inválido ou conta inexistente: `401`, sem execução do grafo.
3. `role_id = 1`: `403`, sem execução do grafo.
4. PostgreSQL indisponível ou lookup com erro: `500`, sem execução do grafo.
5. A API não verifica `exp`; token expirado com assinatura válida seria aceito se chegasse à API, contrariando a premissa operacional.
6. Claims de role, email/body ou `user_id` enviados pelo cliente não alteram o principal.
7. Usuário A não lista, lê, retoma, encerra ou exclui conversa de usuário B.

## Comandos de validação

```powershell
uv run pytest tests/test_auth_token.py tests/test_auth_dependency.py tests/test_auth_repository.py
uv run pytest -m integration tests/integration/test_auth_postgres.py
uv run ruff check src tests
uv run mypy src
```

O teste de integração valida a leitura e a rejeição de escrita/DDL na base efêmera. Os grants efetivos da credencial do ambiente ainda precisam ser comprovados em PostgreSQL de integração.
