# Modelo de identidade

## JWT recebido

| Dado | Origem | Uso |
|---|---|---|
| Token compacto | `Authorization: Bearer` | Assinatura validada com HS256 e `JWT_SECRET`. Nunca persistir ou registrar integralmente. |
| `email` | Claim do JWT | Única claim de identidade consumida; obrigatória, textual e não vazia. |
| `exp` | Eventual claim do emissor | Não validada pela API de IA. A premissa é que o encaminhador só entrega tokens válidos. |
| Segredo HS256 | `JWT_SECRET` em ambiente | Compartilhado entre emissor e API; nunca enviado ao cliente nem versionado. |

## Conta e principal

- `user_account.email` e `user_account.role_id` são lidos por query parametrizada.
- Email sem registro resulta em `401`; erro operacional do PostgreSQL resulta em `500`.
- `role_id = 1` resulta em `403`; demais roles permitidas pelo escopo atual.
- O principal contém o email canônico da linha encontrada e o `role_id` consultado.
- Claims de cargo, `user_id`, email do body ou query não têm autoridade.

## Identidade de memória

MongoDB, Qdrant, Redis/jobs e estado do grafo usam o email autenticado para ownership e isolamento. Conversas permanecem associadas a exatamente um email; nenhuma identidade do cliente substitui a identidade do principal.
