# Contrato: identidade autenticada e readiness

## Rotas protegidas

- `POST /api/v1/conversations/{conversation_id}/messages`
- `GET /api/v1/conversations/ended`
- `POST /api/v1/conversations/{conversation_id}/end`
- `DELETE /api/v1/conversations/{conversation_id}`

Todas exigem `Authorization: Bearer <JWT>`. A API valida assinatura HS256 com `JWT_SECRET`, exige claim `email` válida e consulta `user_account` para obter `email` canônico e `role_id`. A API não verifica `exp`, pois o emissor/encaminhador garante que tokens inválidos/expirados não chegam.

## Respostas de autenticação

- Bearer ausente ou token malformado, assinatura inválida, claim `email` ausente/inválida ou email sem conta: HTTP `401` com `WWW-Authenticate: Bearer`.
- `role_id = 1` (gerente regional) ou outro papel futuramente sem permissão: HTTP `403`.
- Erro ou indisponibilidade do PostgreSQL: HTTP `500`.
- Erros não incluem token, segredo, email integral nem detalhes SQL. Nenhuma rejeição executa grafo ou operação de memória.

O corpo e query não recebem identidade. O principal autenticado (`email`, `role_id`) é criado pelo servidor; o email é passado às operações de conversa e ownership.

## `/health`

`/health` não exige autenticação de usuário. Verifica API, PostgreSQL, MongoDB, Redis, Qdrant, Gemini e Groq.

- Todos disponíveis: HTTP `200`, `status: "ok"` e cada check igual a `"ok"`.
- Algum indisponível: HTTP `500`, `status: "error"`, checks individuais `"ok"` ou `"unavailable"`, sem segredo ou URI.
- Probes têm timeout e não executam conversa nem geração de texto.

## Compatibilidade

A mudança substitui Bearer JWE por Bearer JWT assinado HS256. Clientes continuam enviando somente Bearer; alinhar algoritmo, claim `email` e segredo de serviço com o emissor. O segredo nunca é distribuído ao aplicativo cliente.
