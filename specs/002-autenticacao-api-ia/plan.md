# Plano: autenticação HS256 na API de IA

**Feature**: `002-autenticacao-api-ia`
**Spec**: [spec.md](spec.md)
**Atualizado**: 2026-10-05

## Fluxo

```text
Bearer JWT -> dependência FastAPI -> AuthenticationService
                                  -> JWTEmailDecoder (HS256, claim email)
                                  -> PostgresAccountRepository (email, role_id)
                                  -> AuthenticatedPrincipal
                                  -> rota/controller/grafo
```

`AuthenticationService.authenticate(token)` coordena a autenticação uma vez. `dependencies.py` recebe o Bearer, chama o serviço e mapeia erros para HTTP. A consulta usa o pool existente, SQL parametrizado e timeout. Nenhum caminho de erro de autenticação inicia o grafo.

## Arquivos

- `src/auth/token.py`: validar somente HS256 com PyJWT, exigir email e não validar `exp`.
- `src/auth/service.py`: chamar decoder, consultar conta, bloquear `role_id = 1` e retornar principal.
- `src/auth/account_repository.py`: manter lookup parametrizado e somente leitura.
- `src/auth/models.py` e `src/auth/errors.py`: manter principal, conta e erros internos mínimos.
- `src/api/dependencies.py`: obter Bearer, montar serviço, mapear `401`/`403`/`500` e registrar códigos seguros.
- `src/config.py` e `.env.example`: substituir keyring JWE por `JWT_SECRET` sem valor real no exemplo.
- `pyproject.toml` e `uv.lock`: substituir `jwcrypto` por `PyJWT`.
- Rotas existentes continuam usando `get_authenticated_principal`; `/health` continua pública.

## Dependências externas e premissas

- O serviço emissor e a API de IA recebem o mesmo segredo forte por configuração protegida. O segredo não é enviado ao aplicativo cliente.
- O emissor é responsável por encaminhar apenas tokens que considera válidos. A API de IA verifica assinatura e claim, mas não `exp`.
- `user_account` e o schema comercial continuam sob ownership da API Spring. A API de IA só precisa de leitura de `email` e `role_id`.

## Entrega e validação

1. Atualizar dependência, decoder, serviço e dependência FastAPI.
2. Adaptar os testes de autenticação existentes para tokens HS256; remover cenários específicos de JWE/rotação.
3. Atualizar documentos de contrato/quickstart que ainda descrevem JWE.
4. Confirmar que as respostas são `401`, `403` e `500` conforme a spec e que os erros não executam o grafo.
5. Confirmar em ambiente de integração os grants somente leitura da credencial PostgreSQL.

O contrato de autenticação foi simplificado. A comprovação dos grants reais de implantação permanece uma verificação operacional separada.
