# Implementation Plan: Persistência de turnos e resumos no Qdrant

**Branch**: `003-memoria-resumos-qdrant` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-memoria-resumos-qdrant/spec.md`

## Summary

Alterar a memória conversacional para manter um documento MongoDB por conversa com seu array de mensagens, mas sem texto de resumo, versão ou marcador de sumarização nesse documento. O resumo e seu marcador de progresso passam a ser lidos e gravados exclusivamente no ponto estável da conversa no Qdrant. Implementar jobs duráveis em MongoDB e entrega por Redis Streams (não existentes neste branch), além de worker, busca semântica, fallback de recentes, exclusão e migração dos dados legados.

O documento MongoDB separado `conversation_summary_jobs` continua permitido porque contém apenas metadados de execução, nunca o texto do resumo. Título e estado da conversa também não são conteúdo de resumo.

## Technical Context

**Language/Version**: Python 3.14 (projeto requer `>=3.14`; lock valida Python 3.14.3).

**Primary Dependencies**: PyMongo 4.18.1, `qdrant-client` 1.19.0, redis-py 8.1.0 (adicionado como dependência direta), Pydantic 2.x, pytest 9.1.1. Qdrant/Mongo existem no código; integração Redis Streams para memória ainda será criada. Redis server precisa ser >=5.0 para Streams/consumer groups; confirmar as versões de Redis/Mongo/Qdrant hospedados antes da ativação/migração.

**Storage**: MongoDB `conversations` para documento e mensagens; MongoDB `conversation_summary_jobs` para metadados de jobs; MongoDB `conversation_summary_locks` para leases técnicas por conversa; Redis Streams para entrega; Qdrant para texto, embedding e progresso do resumo. Não persistir texto de resumo em nenhuma coleção MongoDB.

**Testing**: pytest unitário e de contrato; integração marcada com `integration` e dependente de serviços/containers. `pyproject.toml` exclui integração do comando pytest padrão.

**Target Platform**: Serviço FastAPI Python, execução local/contêiner, conforme o setup existente. O servidor Qdrant/Redis/Mongo em produção ainda precisa ser identificado.

**Project Type**: Serviço web Python com subsistema de memória assíncrona.

**Performance Goals**: Nenhuma meta numérica de latência ou escala foi confirmada nesta feature. Preservar encerramento assíncrono e medir duração/fila/reconciliação durante validação, sem inventar SLA.

**Constraints**: Resumo apenas Qdrant; uma conversa/um documento Mongo; mensagens acrescentadas em ordem; isolamento por `user_id`; jobs de entrega pelo menos uma vez; retries limitados e observáveis; ponto Qdrant estável por conversa; resumo não pode ser recriado após exclusão; a rubrica de interação conversacional no MongoDB continua atendida pelas mensagens.

**Scale/Scope**: `src/memory/`, integração com o endpoint/worker de encerramento e busca de contexto, dados legados e testes correspondentes. Não inclui autenticação (feature 002), novo comportamento dos agentes, política de retenção automática nem contrato público de nova rota de exclusão.

## Constitution Check

| Gate | Resultado | Evidência/ação |
|---|---|---|
| Spec-first e rastreabilidade | PASS | Spec aprovada; requisitos FR-001–FR-015 e critérios SC-001–SC-010 orientam este plano. |
| Status explícito e sem decisões silenciosas | PASS | Decisões de produto e campo físico `messages` estão confirmadas na spec; parâmetros operacionais permanecem como decisões técnicas de implementação, não como novas regras de produto. |
| Contratos e responsabilidades | PASS | Mongo mantém histórico; Qdrant mantém texto e vetor; jobs Mongo/Redis mantêm só metadados e entrega. |
| Privacidade e isolamento | PASS | Toda leitura de candidato Qdrant é validada contra dono/estado atual no Mongo; exclusão deve limpar ambos e bloquear jobs tardios. |
| Testes e evidências | PASS | Plano inclui unitários, integração Mongo/Qdrant/Redis, regressão de busca/fallback, migração e evidências ligadas aos FRs. |
| Restrições acadêmicas | PASS | MongoDB continua persistindo interação conversacional; Qdrant é memória de resumo, sem retirar o uso obrigatório do Mongo. |

**Post-design gate**: PASS sob as mesmas condições. A versão do servidor Qdrant, estratégia concreta de coordenação e janela numérica de retry precisam ser confirmadas antes da implementação; são decisões técnicas do plano, não ambiguidades de produto.

## Project Structure

### Documentation (this feature)

```text
specs/003-memoria-resumos-qdrant/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── memory-persistence.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
src/memory/
├── contracts.py                  # contratos de mensagem, conversa e resumo
├── mongo_repository.py           # documento da conversa e leitura de propriedade/estado
├── message_service.py            # append idempotente das mensagens
├── summary_jobs.py               # modelo/estados de job (sem texto de resumo)
├── summary_job_repository.py     # estado durável, índices, claim e retry
├── summary_lock_repository.py    # lease/fencing por conversa, compartilhada com exclusão
├── summary_scheduler.py          # fechamento interno e criação idempotente do job
├── summary_queue.py              # relay e publicação Redis Streams
├── qdrant_summary_indexer.py     # upsert e leitura do ponto de resumo
├── service.py                    # busca semântica e fallback recentes
├── summary_reconciler.py         # localizar pontos ausentes/desatualizados
└── worker/
    ├── summary_job_worker.py     # consumer group, recuperação, lease e retry limitado
    ├── run_summary_worker.py     # entry point do consumer e relay em processo separado
    └── summarizer_end_conversation.py

scripts/
└── migrate_conversation_summaries.py  # dry-run/backfill/unset por lote

tests/
├── test_memory_message_service.py
├── test_memory_summary_context.py
├── test_qdrant_summary_indexer.py
├── test_summary_jobs.py
├── test_summary_job_worker.py
├── test_summary_reconciler.py
├── test_conversation_summary_migration.py
└── integration/
    └── test_memory_mongo_repository.py
```

**Structure Decision**: Manter a arquitetura em `src/memory/` e integrar jobs/relay/worker ao endpoint interno de encerramento já existente na API. O worker e relay rodam em processo separado da API. `closure_key` estável é criada uma vez pela aplicação no limite interno de encerramento, gravada no job e encaminhada pelo Redis apenas como `job_id`; não introduz rota pública. Não criar coleção de conversa paralela. O campo físico confirmado continua `messages`.

## Design Approach

1. **Fonte e limites de persistência**: MongoDB é fonte do histórico de mensagens e metadados de conversa; Qdrant é fonte exclusiva do conteúdo do resumo e de seu progresso; job repository guarda somente estado operacional.
2. **Fechamento assíncrono**: a camada interna de encerramento gera uma `closure_key` estável e persiste (ou recupera) o job por `(conversation_id, closure_key)`. Um relay publica jobs ainda não publicados em Redis Streams; o evento carrega só `job_id`. O worker lê snapshot de mensagens, busca resumo/progresso no Qdrant, sumariza somente o sufixo não coberto, faz upsert e só então conclui job/ack. Um relay/reclaim repara falhas entre persistência Mongo e publicação Redis.
3. **Proteção contra stale writes**: usar lease Mongo com fencing token/heartbeat por conversa, compartilhada por todos os jobs e pela futura exclusão; revalidar lease e status/progresso imediatamente antes do upsert. A exclusão adicionará tombstone operacional na T025 para impedir que consumidor com snapshot antigo recrie o ponto.
4. **Busca de contexto**: o vetor e o texto vêm do Qdrant. MongoDB valida `user_id`, conversa existente e status encerrado; deixa de ser autoridade de texto/versão do resumo. O fallback recente também é migrado para leitura Qdrant filtrada/ordenada.
5. **Migração gradual**: primeiro garantir que o novo caminho lê/escreve Qdrant; em seguida validar/reutilizar pontos existentes e reconstruir ausentes a partir das mensagens; por último remover `summary`, `summary_version` e `summarized_through_message_id` dos documentos Mongo. Se um ponto falhar, manter o documento legado intacto para nova tentativa. Pós-migração, recuperação é regenerar do histórico, não restaurar o texto do resumo no Mongo.
6. **Título**: permanece metadado da conversa fora do escopo de armazenamento do resumo. Quando gerado com base no resumo, o texto pode ser usado transitoriamente pelo worker; apenas o título é gravado no Mongo.

## Migration and Rollback

- Produzir relatório de pré-migração com contagens por estado, presença/validade do ponto Qdrant e campos legados de resumo; não incluir texto de resumo em logs/telemetria.
- Fazer backfill por conversa: validar ownership/status e ponto Qdrant existente; preencher progresso ausente quando recuperável; gerar resumo do histórico se o ponto estiver ausente/inválido; ler novamente o ponto e validar metadados antes de remover campos legados.
- Tornar o backfill idempotente e retomável, com limite de lote, cursor e relatório de falhas. Não remover dados de conversas cujo ponto Qdrant não tenha sido verificado.
- Aplicação pós-cutover não lê nem grava conteúdo de resumo no Mongo. Remover campos legados com `$unset` apenas após verificação por conversa/lote.
- Reversão não reidrata resumo no Mongo: corrigir/recriar ponto a partir do histórico de mensagens. A migração mantém documentos sem alteração quando a escrita/validação Qdrant falhar.
- Exclusão é operação idempotente: estado de exclusão/job durável antecede a limpeza final; apagar ponto Qdrant e documento da conversa, reconhecer job e reconciliar operações interrompidas. O marcador operacional temporário não guarda texto de resumo.

## Risks and Mitigations

| Risco | Mitigação no plano |
|---|---|
| Job gravado e publicação Redis falha/interrompe | Outbox no próprio job (`published_at`), relay retomável, consumer group e reclaim de pendentes/leases expirados. |
| Dois fechamentos escrevem fora de ordem | Coordenação por conversa, watermark monotônico e revalidação antes do upsert. |
| Qdrant indisponível durante migração | Não remover campos legado daquele documento; retry/reconciliação posterior. |
| Exclusão concorre com job em processamento | Estado/tombstone de exclusão, claim/serialização e limpeza idempotente com verificação de ausência do ponto. |
| Campo de ordenação não indexado no Qdrant | Criar/verificar índice de payload `updated_at`; validar versão do servidor e comportamento de `scroll(order_by)` no ambiente. |
| Histórico excede limite BSON de 16 MiB | Manter limite/monitoramento como decisão de arquitetura separada; testar mensagem/documento próximo ao limite antes de release. Não mover texto de resumo para Mongo como workaround. |

## Complexity Tracking

Não há violação da constituição proposta. A coordenação adicional de jobs é necessária para atender idempotência, exclusão concorrente e recuperação sem duplicar o resumo no Mongo.
