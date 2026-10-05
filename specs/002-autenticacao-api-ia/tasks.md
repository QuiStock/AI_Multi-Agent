# Tarefas: autenticação HS256 na API de IA

**Spec**: [spec.md](spec.md)
**Plano**: [plan.md](plan.md)

- [x] T001 Substituir decoder JWE/RSA/keyring por validação HS256 e extração da claim `email` em `src/auth/token.py`; não validar `exp`.
- [x] T002 Fazer `AuthenticationService.authenticate(token)` coordenar decode, consulta de conta e regra de cargo; `dependencies.py` chama o método uma vez.
- [x] T003 Trocar configuração de keyring por `JWT_SECRET` em `src/config.py` e `.env.example`; substituir `jwcrypto` por PyJWT em `pyproject.toml`/`uv.lock`.
- [x] T004 Adaptar os testes de autenticação existentes de JWE para HS256.
- [x] T005 Alinhar a spec, plano, contrato, modelo de dados, quickstart, checklist, ADR e guias ativos para HS256.
- [ ] T006 Executar a validação solicitada pelo responsável do projeto e registrar os resultados em `quickstart.md`.
- [ ] T007 Confirmar em PostgreSQL de integração os grants efetivos somente leitura da credencial da API de IA.

## Critério de conclusão

Rotas protegidas recebem o principal autenticado antes de controller/grafo; token inválido ou conta inexistente retorna `401`, `role_id = 1` retorna `403`, falha PostgreSQL retorna `500`; `/health` permanece público. A API valida a assinatura HS256 e claim `email`, sem validar `exp`, conforme premissa operacional aprovada.
