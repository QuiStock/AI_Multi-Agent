# Contrato: identidade autenticada e readiness

## Rotas protegidas de conversa

Aplica-se a `POST /api/v1/conversations`, `GET /api/v1/conversations/ended` e `POST /api/v1/conversations/{conversation_id}/end` (confirmar rotas exatas contra o código no início da implementação). Todas exigem `Authorization: Bearer <JWE>` com `alg=RSA-OAEP-256` e `enc=A256GCM`. A camada anterior à API garante que tokens expirados não sejam encaminhados; a API não valida expiração. A chave JWE é fornecida por ambiente e a única claim consumida é `email`. Durante rotação, o `kid` do cabeçalho protegido seleciona a chave privada; antiga e nova ficam disponíveis temporariamente.

### Autenticação/autorização

1. Falta de Bearer, formato inválido, decrypt/claim inválidos ou email sem conta → HTTP `401`.
2. Consulta de identidade ao PostgreSQL indisponível/falha inesperada → HTTP `500`.
3. `role_id = 1` → HTTP `403`.
4. Só depois da validação o controller recebe um principal do servidor (`email`, `role_id`); a chamada ao grafo não começa em erros.
5. Erros são respostas genéricas e não contêm token, chave, claim completa ou detalhes SQL.

### Request/response

- Conversa: body mantém mensagem, timestamp e opções conversacionais existentes; remover `user_id`. A identidade vem só do principal autenticado.
- Listagem de conversas encerradas: remover `user_id` da query; usar o principal autenticado.
- Encerramento: body não recebe identidade; usar o principal autenticado.
- Respostas de sucesso preservam os schemas funcionais existentes, salvo remoção de campos de identidade que hoje sejam expostos.
- Incluir `WWW-Authenticate: Bearer` em resposta `401`, sem detalhar a causa específica da credencial.

## `/health`

- Sem autenticação de usuário; verifica prontidão da API e PostgreSQL, MongoDB, Redis, Qdrant, Gemini e Groq.
- Todas disponíveis → HTTP `200`:

```json
{
  "status": "ok",
  "checks": {
    "api": "ok",
    "postgresql": "ok",
    "mongodb": "ok",
    "redis": "ok",
    "qdrant": "ok",
    "gemini": "ok",
    "groq": "ok"
  }
}
```

- Qualquer indisponível/timeout → HTTP `500`, `status: "error"`; manter cada check em `"ok"` ou `"unavailable"`, sem incluir segredos/URIs:

```json
{
  "status": "error",
  "checks": {
    "api": "ok",
    "postgresql": "ok",
    "mongodb": "unavailable",
    "redis": "ok",
    "qdrant": "ok",
    "gemini": "ok",
    "groq": "ok"
  }
}
```
- Probe tem timeouts limitados e não executa geração de texto nem operação de conversa.

## Compatibilidade

Mudança incompatível no contrato de entrada: clientes substituem `user_id` por Bearer JWE. Rejeitar `user_id` no payload (extra forbid existente) e não manter fallback. Coordenar rollout com cliente e contrato da API externa que emite o token; a API externa não é implementada aqui.
