# Checklist: autenticação HS256

## Escopo confirmado

- [x] A FastAPI só recebe token; login e emissão permanecem com o emissor existente.
- [x] O JWT é assinado com HS256 e validado com segredo compartilhado de ambiente.
- [x] A API consome `email` e obtém `role_id` do PostgreSQL.
- [x] A API não valida `exp`; assume que o emissor/encaminhador só repassa tokens válidos.
- [x] Erros estão definidos: `401` para token/conta inválidos, `403` para cargo bloqueado e `500` para falha PostgreSQL.
- [x] Rejeições ocorrem antes do grafo; `/health` permanece público.
- [x] `role_id = 1` é bloqueado no escopo atual.

## Implementação

- [x] Decoder HS256, serviço de autenticação, dependência HTTP, configuração e dependência PyJWT adaptados.
- [x] Casos de teste existentes adaptados ao novo token.
- [ ] Executar suíte e registrar resultados em `quickstart.md`.
- [ ] Verificar grants de somente leitura contra PostgreSQL de integração.
