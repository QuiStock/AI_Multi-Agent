# Data Model: Memória conversacional

**Feature**: `003-memoria-resumos-qdrant`
**Status**: Proposta técnica alinhada aos requisitos confirmados; nomes físicos finais precisam ser revisados antes da implementação.

## 1. Conversation document — MongoDB `conversations`

Um documento por conversa, identificado por `_id`; mensagens ficam em array ordenado. A amostra do usuário representa essa granularidade. O campo `resumo` não existe no estado final.

| Campo lógico | Tipo | Regra |
|---|---|---|
| `_id` / `conversation_id` | string | Identificador estável da conversa; `_id` é a chave física já usada pelo repositório. |
| `email` | string | Obrigatório desde a criação da nova coleção; identidade canônica derivada do JWT; todas as consultas de conversa filtram pelo email autenticado no servidor. Não manter campo de identidade `user_id` na nova coleção. |
| `status` | `active \| ended \| deleting` | `deleting` é estado transitório proposto para garantir limpeza cross-store. |
| `started_at`, `updated_at`, `ended_at` | timestamp UTC | Ordenação/listagem; campo ausente/nulo de `ended_at` enquanto ativa. |
| `title` | string ou nulo | Metadado, não é resumo; pode continuar no Mongo. |
| `messages` (array conceitual `mensagens` da amostra) | `StoredMessage[]` | Append em ordem; não persistir resumo neste campo nem em campo irmão. |
| `total_turns` | inteiro não negativo | Contagem derivada/compatível com comportamento existente; validar se é necessária na revisão do contrato. |

`StoredMessage`:

| Campo | Tipo | Regra |
|---|---|---|
| `message_id` | string | Estável e único na conversa; código atual deriva de `request_id` e role, permitindo append idempotente. |
| `role` | `user \| assistant` | Mensagem do usuário ou resposta final do assistente. |
| `content` | string | Texto persistido sujeito às políticas existentes; não incluir reasoning/tool intermediária. |
| `created_at` | timestamp UTC | Data/hora com timezone; desempate deve respeitar ordem append do array. |
| `consulted_agents` | string[] ou ausente | Apenas em mensagem do assistente; metadado já previsto pelo contrato atual. |

**Remover do documento de conversa**: `summary`, `summary_version`, `summarized_through_message_id`. Não criar alias para esses valores no Mongo.

### Relações e invariantes

- Uma conversa pertence a exatamente um usuário.
- Uma conversa contém zero ou mais mensagens, persistidas no mesmo documento.
- Um turno de usuário/assistente é uma relação lógica entre mensagens; não é outro documento Mongo.
- Mensagem duplicada com mesmo `message_id` não é acrescentada novamente.
- O limite MongoDB de 16 MiB por documento continua aplicável; política de compactação/retention é questão fora do escopo e precisa de monitoramento.

## 2. Summary job metadata — MongoDB `conversation_summary_jobs` (a criar)

Coleção operacional nova; não contém texto ou embedding de resumo. `closure_key` é gerada uma vez na camada de aplicação ao iniciar o encerramento e é reutilizada em retries do mesmo evento. O job ID enviado ao Redis é uma referência a este documento, nunca o conteúdo do resumo.

| Campo | Tipo | Regra |
|---|---|---|
| `_id` / `job_id` | string | Identidade do job. |
| `conversation_id`, `email` | string | Escopo e identidade do usuário derivados do servidor. |
| `closure_key`, `request_id` | string/nulo | `closure_key` estável deduplica `(conversation_id, closure_key)`; quando disponível, é derivada de `conversation_id` + `request_id` estável, que também serve à rastreabilidade. |
| `status` | `queued \| processing \| completed \| failed \| superseded` | Estados observáveis; `processing` expira via lease; `superseded` significa conversa retomada/removida antes do job; falha terminal pode ser reprocessada por operação autorizada. |
| `attempts` | inteiro | Contagem limitada; estado da tentativa fica no job, não no resumo. |
| `created_at`, `updated_at`, `published_at`, `next_attempt_at`, `lease_until` | timestamp UTC/nulo | Controle de publicação, backoff e recuperação de worker inativo. |
| `lease_owner` | string/nulo | Consumidor que reivindicou o job; metadado operacional. |
| `last_error` | string segura/nulo | Diagnóstico truncado/categorizado, sem segredo, conteúdo de resumo ou prompt privado. |

Índices a criar: único `(conversation_id, closure_key)` e recuperação por `(status, next_attempt_at, created_at)` para jobs não publicados, retries devidos e leases vencidos.

**Redis Stream**: evento contém apenas `job_id`; Mongo é a fonte durável. O relay publica jobs sem `published_at` e só registra publicação após o `XADD`; se cair entre `XADD` e atualização do Mongo, a publicação duplicada é segura porque o worker reivindica o mesmo job idempotente.

## 2.1 Lease por conversa — MongoDB `conversation_summary_locks` (a criar)

Um documento de coordenação por conversa, separado do histórico e dos jobs. A mesma lease é compartilhada futuramente pelo worker de resumo e pela exclusão.

| Campo | Tipo | Regra |
|---|---|---|
| `_id` | string | `conversation_id`, identidade única da trava. |
| `owner` | string | Identificador técnico do worker/operação que possui a lease. |
| `lease_until` | timestamp UTC | Expiração para recuperação após queda do processo; heartbeat renova enquanto trabalha. |
| `fencing_token` | inteiro crescente | Incrementa em cada nova aquisição para impedir que proprietário antigo renove/libere lease nova. |

Não armazena mensagem, resumo, prompt ou conteúdo de negócio.

## 3. Summary point — Qdrant collection de memória

Um ponto estável por conversa (`point_id` determinístico a partir de `conversation_id`). A vetorização usa o texto do resumo. O resumo só aparece neste payload persistente.

| Payload | Tipo | Regra |
|---|---|---|
| `memory_type` | keyword | `conversation_summary`. |
| `conversation_id`, `email` | string/keyword | Filtrar e validar identidade; payload não substitui autorização Mongo. |
| `status` | keyword | Apenas `ended` é elegível à recuperação. |
| `title` | string/nulo | Metadado de conversa; pode ser copiado do Mongo. |
| `summary` | string | Texto do resumo; fonte persistente exclusiva. |
| `summary_version` | inteiro positivo | Avança por publicação aceita; não exige cópia Mongo. |
| `summarized_through_message_id` | string | Watermark inclusivo da última mensagem resumida; comparar com ordem `messages`. |
| `updated_at` | timestamp sortable | Ordenação do fallback recente; exige índice de payload compatível. |

## 4. State transitions

```text
Conversation: active -> ended -> active (resume)
                       \-> deleting -> removed from Mongo and Qdrant

Summary job: queued -> processing -> completed
                         |          |
                         +-> queued <-+ (retryable, after next_attempt_at)
                         +-> failed (retry limit; observable/reprocessable)
                         +-> superseded (conversation is no longer eligible)

Qdrant summary: absent/stale -> current at message watermark N
```

`deleting` e `next_attempt_at` são propostas técnicas para tornar a operação repetível; validar contrato e implementação no design de tasks.
