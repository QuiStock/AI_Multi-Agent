# Research: Memória com resumo exclusivamente no Qdrant

**Feature**: `003-memoria-resumos-qdrant`
**Date**: 2026-09-30

## Current implementation evidence

1. **Documento e mensagens** — `MongoConversationRepository` já mantém um documento por conversa e acrescenta mensagens no campo físico confirmado `messages`. `StoredMessage.message_id` é derivado de `request_id` e papel; `append_message` usa atualização atômica e reconhece IDs já persistidos. Isso satisfaz a granularidade funcional aprovada. A amostra em português chama conceitualmente o array de `mensagens`; os demais nomes físicos existentes serão preservados conforme contrato.
2. **Resumo duplicado** — `ConversationDocument`, `ConversationSummarySnapshot`, `SummaryCommit` e métodos do repositório mantêm `summary`, `summary_version` e `summarized_through_message_id` no documento `conversations`. O worker primeiro grava o resumo no Mongo e depois chama o indexador Qdrant. Esse é o caminho a substituir.
3. **Fila ainda não implementada neste branch** — não foram encontrados `conversation_summary_jobs`, publisher/consumer Redis Streams nem worker que processe jobs. `redis` não era dependência direta; agora foi adicionado a `pyproject.toml` e `uv.lock` para esta implementação. Essas peças serão criadas nesta feature; não se deve tratar o fluxo como infraestrutura pré-existente.
4. **Ponto Qdrant** — `QdrantSummaryIndexer` gera ID determinístico por `conversation_id` e faz upsert de payload com texto, `summary_version`, owner, status, título e data. Não grava atualmente `summarized_through_message_id` e não oferece leitura do resumo anterior. A camada deverá permitir recuperar o ponto por ID e gravar marcador de progresso.
5. **Busca semântica/fallback** — `SummaryContextService` recupera candidatos do Qdrant, mas valida versão e recupera o texto do Mongo; se não encontra candidatos válidos, busca os resumos recentes no Mongo. Ambos os caminhos devem usar Qdrant como fonte do texto, mantendo consulta Mongo apenas para propriedade/estado/título.
6. **Exclusão** — Foi localizado apenas `delete_thread` do checkpointer; não há operação de exclusão do documento conversacional nem do ponto Qdrant em `src/memory`. A limpeza cross-store e sua proteção contra jobs em andamento são trabalho novo desta feature.
7. **Worker de resumo e título** — O worker incremental usa resumo e marcador do Mongo como entrada. O título é salvo em Mongo e não é o resumo; pode continuar armazenado ali, usando temporariamente o texto recém-gerado/lido do Qdrant.

## Decisions and rationale

### R1 — Fonte de verdade do resumo

- **Decision**: texto do resumo fica apenas no payload Qdrant. MongoDB mantém o documento da conversa e mensagens; a coleção de jobs mantém só metadados.
- **Rationale**: decisão confirmada na spec pelo usuário; elimina a duplicação atual. Qdrant também precisa fornecer o resumo para recuperação semântica e para sumarização incremental.
- **Alternatives considered**: manter cópia Mongo como fonte durável (rejeitada pela decisão confirmada); cachear no Redis (não é fonte persistente aprovada e duplicaria o dado).

### R2 — Progresso incremental

- **Decision**: incluir no payload do ponto Qdrant um marcador de mensagem até a qual o resumo foi produzido, além da versão/data. Worker usa resumo atual do Qdrant + mensagens posteriores ao marcador. A gravação da mesma conversa atualiza o mesmo ponto determinístico.
- **Rationale**: permite retries sem reaplicar mensagens já resumidas e fornece estado comparável ao histórico Mongo para reconciliação.
- **Alternatives considered**: guardar marcador junto à conversa Mongo (evitado para manter metadados do resumo fora do documento de conversa); resumir todo o histórico a cada encerramento (mais simples, porém reprocessa todo o conteúdo e não reaproveita resumo incremental aprovado).

### R3 — Entrega e retries

- **Decision**: implementar Mongo job metadata + Redis Streams, com semântica at-least-once, job idempotente por conversa/fechamento, limite de tentativas, erro seguro observável e reprocessamento explícito de falha terminal. Um relay recupera jobs persistidos ainda não publicados.
- **Rationale**: Mongo mantém estado durável; Redis Streams entrega IDs e permite reentrega sem duplicar conteúdo do resumo.
- **Alternatives considered**: processar resumo na requisição de encerramento (contraria resposta assíncrona confirmada); nova fila ou broker (sem benefício comprovado para o escopo).
- **Closure key — confirmado em 2026-10-01**: chave estável criada pela camada de aplicação no evento interno de encerramento, antes de agendar. A mesma chave acompanha o job em Mongo e o evento Redis; repetições do mesmo encerramento reencontram o mesmo job. Ela não é um campo solicitado ao usuário nem uma rota pública nova. O backend pode derivá-la deterministicamente de `conversation_id` + `request_id` estável; não gerar nova chave por retry.
- **Redis server requirement**: Redis Streams/consumer groups requerem Redis 5.0 ou superior. O reclaim foi projetado com `XPENDING` + `XCLAIM` para não exigir `XAUTOCLAIM` (Redis 6.2). A versão do serviço hospedado ainda precisa ser verificada antes de ativar em produção.

### R4 — Fallback de conversas recentes

- **Decision**: recuperar os pontos encerrados do próprio usuário no Qdrant, ordenados por payload `updated_at` descendente, excluindo a conversa atual; validar propriedade e estado no Mongo antes de devolver até o limite vigente. Manter índice de payload compatível com filtro/ordenação.
- **Rationale**: elimina dependência do texto no Mongo e mantém o comportamento de fallback recente.
- **Alternatives considered**: percorrer todos os pontos e ordenar localmente (menos eficiente à medida que a coleção cresce); devolver candidatos de busca semântica como fallback (não preserva o requisito de “mais recentes”).
- **Evidence**: o painel do cluster Qdrant Cloud `Interdisciplinar` mostrou versão **v1.19.1** em 2026-10-01. A documentação oficial informa que `scroll` com `order_by` de payload está disponível desde v1.8.0 e exige índice de payload apropriado; portanto a versão observada atende ao requisito de versão. O índice do campo usado (`updated_at`) ainda deve ser criado/verificado na implementação. [Qdrant: Points, Scroll e Order By](https://qdrant.tech/documentation/concepts/points/).

### R5 — Ordenação concorrente e exclusão

- **Decision**: coordenar atualizações por conversa com lease Mongo de fencing token e heartbeat, revalidar lease/estado/maior watermark imediatamente antes do upsert e usar tombstone/job durável para exclusão; nenhum job pode reindexar conversa em exclusão/concluída. O watermark é o `message_id` estável da última mensagem incluída e sua ordem é resolvida pelo array canônico Mongo, nunca por timestamp. Operações de exclusão/upsert devem ser repetíveis.
- **Rationale**: Qdrant e MongoDB não compartilham transação; ordem entre escrita vetorial, reentrega e exclusão precisa ser explícita.
- **Alternatives considered**: depender somente de cancelamento do job (não cobre worker já executando); apagar apenas Mongo (deixa resumo recuperável no Qdrant); apagar apenas Qdrant (não remove histórico solicitado).
- **Open technical verification**: validar lease expirada/heartbeat e a versão Redis >=5.0 no serviço hospedado. O contrato exige coordenação por conversa e revalidação de tombstone antes do upsert; a implementação deve provar que job concorrente/atrasado não ressuscita o ponto.

### R6 — Cutover de coleções sem preservar o histórico antigo

- **Decision**: descartar o histórico antigo; provisionar novas coleções MongoDB e Qdrant vazias. Novos documentos, jobs e payloads usam email como identidade desde a criação; não migrar user_id, mensagens, resumos ou jobs antigos.
- **Rationale**: decisão explícita do usuário de não levar o histórico antigo para as novas coleções.
- **Operational safeguard**: antes de qualquer remoção física, validar ambiente e identificadores exatos das coleções alvo. Rollback de aplicação não restaura histórico descartado.

## Dependency and project constraints

- Projeto exige Python `>=3.14`; `uv.lock` resolve Python 3.14.3, PyMongo 4.18.1, qdrant-client 1.19.0, redis 8.1.0 e pytest 9.1.1.
- Testes de integração usam o marcador `integration`; o default pytest exclui esses testes.
- O histórico antigo será descartado; o cutover deve provisionar coleções novas e vazias e validar os alvos antes da remoção física das coleções antigas. Não haverá script de backfill de mensagens/resumos.
- **T002 — ambiente-alvo**: Qdrant Cloud `Interdisciplinar` foi verificado no painel em 2026-10-01: **v1.19.1**, compatível com `scroll.order_by` (disponível desde v1.8.0), condicionado ao índice de payload de `updated_at`. MongoDB Atlas e Redis hospedado não foram verificados nesta consulta; suas versões permanecem desconhecidas, mas não há no plano atual uma dependência de funcionalidade específica dessas versões. Não inferir versões de servidores a partir das bibliotecas cliente instaladas.
- Não foi encontrado contrato HTTP público de exclusão da conversa nesta implementação. O plano cobre a operação interna de persistência/limpeza; endpoint público e UX devem ser tratados como extensão explícita se forem necessários.
- Proposta de nomes de campos: manter nomes ingleses existentes no código para reduzir migração, traduzindo o exemplo do usuário semanticamente; confirmar antes de implementação caso o grupo queira nomes físicos em português.

## Status classification

- `implementado` (estado atual): documento Mongo único com array de mensagens; ponto Qdrant determinístico; resumo atualmente duplicado em Mongo e Qdrant. Busca e recuperação semântica do resumo migradas em parte durante US2.
- `proposto` (detalhe técnico aprovado/em implementação): coleção Mongo de jobs, relay/outbox Redis Streams, consumer group, lease compartilhada por conversa e backoff limitado; `closure_key` estável derivada do request idempotente no limite interno de encerramento.
- `confirmado` (alvo): Mongo conserva conversa e array físico `messages` sem resumo; Qdrant guarda texto e watermark do resumo; atualizações assíncronas, idempotentes, reconciliáveis e exclusão de ambos os dados. Mensagens são ordenadas pelo array; o watermark referencia o `message_id` estável. O fallback usa pontos Qdrant recentes ordenados por `updated_at`, com validação de propriedade/estado no Mongo.
- `proposto` (detalhe técnico): estratégia concreta de lease/claim/fencing para serialização e tombstone; valores do backoff limitado e agenda de reconciliação.
- `aberto`: exposição de rota pública de exclusão. As versões gerenciadas de MongoDB Atlas e Redis não foram consultadas, mas não há dependência específica delas nesta feature. A decisão do campo `messages` foi confirmada em 2026-09-30 e a versão Qdrant Cloud v1.19.1 foi verificada em 2026-10-01.
- `divergente`: a spec legada fora de `specs/` diz que Mongo conserva cópia durável do resumo; a decisão aprovada nesta feature substitui essa regra para a IA.
