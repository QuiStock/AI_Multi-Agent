# Data Model: Autenticação e identidade

## Entidades

### Credencial recebida

| Campo | Origem | Regra |
|---|---|---|
| compact JWE | `Authorization: Bearer` | Obrigatório em toda rota de conversa; `alg=RSA-OAEP-256`, `enc=A256GCM`; nunca persistido ou registrado integralmente. |
| `email` | única claim consumida pela API | Obrigatória, não vazia e usada para lookup. Regras de normalização/case-sensitivity devem corresponder ao banco e serão confirmadas no contrato de implementação. Nenhum outro claim será consumido. |
| chave privada RSA | `JWE_PRIVATE_KEYS_JSON` fornecida em `.env` | JSON que associa `kid` a PEM privado RSA; cada chave corresponde à chave pública usada pelo emissor e tem mínimo 2048 bits. `.env` real é mantido pelo operador; `.env.example` contém apenas nome e instrução, sem segredo. Biblioteca: `jwcrypto`. |

### Conta consultada (`user_account`)

| Campo | Tipo lógico | Uso |
|---|---|---|
| `email` | texto | Predicado parametrizado de igualdade; identificador canônico propagado após validação. |
| `role_id` | inteiro | Autorização; valor `1` é gerente regional e recebe `403`. |

Somente leitura via `POSTGRES_DSN`, com credencial exclusiva do serviço. Nenhuma escrita, DDL, migração ou concessão de privilégio pela API de IA. A tabela/schema é responsabilidade da API Spring. Ausência de linha resulta em `401`; falha operacional do PostgreSQL resulta em `500`.

### Principal autenticado

| Campo | Regra |
|---|---|
| `email` | Claim associada a linha existente; identidade canônica e obrigatória para fluxo, autorização e memória. |
| `role_id` | Papel retornado pela consulta; `1` bloqueado, demais papéis permitidos pelo escopo atual da feature. |

Não aceitar `email`, `role_id` ou `user_id` do cliente como substituto dos valores confiáveis do principal.

### Identidade de memória

- MongoDB: campo de proprietário da conversa passa a `email`; todas as queries de ownership incluem conversation id + email.
- Qdrant: payload e filtros de resumo usam `email`.
- Redis/job de resumo: identidade serializada é `email`; worker reutiliza esse escopo em Mongo e Qdrant.
- Não haverá backfill. Coleções novas vazias são responsabilidade do rollout de memória; esta feature não executa exclusão de dados existentes.

## Relações e cardinalidade

- Uma linha de `user_account` identificada pelo email validado autoriza zero ou mais conversas.
- Cada conversa pertence a exatamente um email.
- Cada job de resumo refere-se a uma conversa e ao mesmo email proprietário; o worker deve validar ambos antes de alterar índice/persistência.

## Privacidade e retenção

- JWT, chave e DSN nunca entram em logs; erros públicos não revelam se houve falha de parsing, decrypt ou detalhes do banco além do status/código aprovado.
- Email é dado pessoal: logs operacionais devem evitar conteúdo integral; quando correlação for necessária, preferir request id e métricas agregadas.
