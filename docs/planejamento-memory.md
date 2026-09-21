# Planejamento do módulo de memória

**Status:** arquitetura-alvo definida para a branch `memory`; endpoints e interface ficam para a branch `api`.
**Atualizado:** 2026-09-21

## Fluxo

```text
START -> input_guardrail -> enrich_context -> router
                                      router -> [tool opcional: buscar resumos] -> router
                                      router -> capacidade -> compiler -> judge -> ...
```

- `enrich_context` roda depois do guardrail de entrada e antes do router.
- Em conversa nova, a etapa não busca resumos. Em retomada, valida usuário e conversa no MongoDB, carrega o histórico ordenado e o coloca em `GraphState.messages`. A mensagem atual entra uma única vez.
- O router decide pela verbalização sanitizada se precisa de memória anterior. Se precisar, chama `search_conversation_summaries`; a busca não é disparada automaticamente pelo grafo.
- A tool retorna resumos estruturados para o router. Não os injeta como mensagens de usuário ou assistente nem os incorpora ao resumo durável da conversa atual.

## Ciclo de vida

1. O app inicia uma conversa ativa e envia `conversation_id` e identidade autenticada (`user_id`) à API.
2. Enquanto ativa, a conversa continua no estado principal. O MongoDB mantém o histórico durável conforme o serviço de mensagens.
3. Ao encerrar, o serviço garante as mensagens no MongoDB e seleciona as posteriores a `summarized_through_message_id`. No primeiro resumo, usa o histórico disponível; nos seguintes, atualiza o resumo anterior da mesma conversa usando apenas essa diferença de mensagens. Resumos recuperados de outras conversas nunca entram nessa atualização. Persiste nova versão e marcador. Se ainda não houver título, gera-o a partir do resumo com `gemini-2.5-flash-lite` (modelo estruturado centralizado em `llm_factory`) e salva-o uma única vez no MongoDB; depois gera embedding e faz upsert do ponto no Qdrant com o título persistido. Falha na geração do título não impede salvar/indexar o resumo e permite nova tentativa no próximo encerramento.
4. A sessão encerrada aparece na lista do app por título. A API fornece essa lista usando uma consulta por `user_id`; a UI e os endpoints são escopo da branch `api`.
5. Ao selecionar uma sessão encerrada, a API sinaliza `is_resuming_conversation=true` no estado e usa o mesmo `conversation_id`. A memória valida propriedade, reabre a conversa e restaura `messages`. Mensagens de continuação normal não ativam essa etapa. A sessão ativa não é elegível na busca semântica.
6. Ao encerrar novamente, o resumo e o mesmo ponto Qdrant são atualizados, sem criar uma conversa ou ponto duplicado.

A gravação e o fechamento devem ser idempotentes. MongoDB é a fonte durável; o Qdrant é índice de busca e seus candidatos são revalidados no MongoDB. Falhas de sumarização ou indexação precisam permitir retry/reconciliação.

## Identificadores e dados

- `message_id`: único por mensagem, usado para deduplicar gravações.
- `conversation_id`: estável durante retomadas; identifica o documento MongoDB e o ponto Qdrant.
- `user_id`: identidade autenticada, aplicada pelo servidor em toda leitura, escrita e busca.
- `summarized_through_message_id`: última mensagem incorporada ao resumo; delimita a diferença incremental sem comparar IDs lexicograficamente.
- MongoDB: uma coleção `conversations`, um documento por conversa, com título, status, timestamps, mensagens, resumo e versão. Usar `conversation_id` como `_id`; não duplicar `session_id` sem necessidade contratual.
- Qdrant: coleção de memória separada do FAQ; um ponto por conversa, com `user_id`, `conversation_id`, `status`, `title`, `summary` e `summary_version` no payload.

## Busca semântica acionada pelo router

- Consulta derivada da mensagem atual já sanitizada.
- Filtrar no Qdrant pelo usuário autenticado, tipo de memória e status encerrado; excluir a conversa atual.
- Considerar até 3 candidatos, mantendo apenas score `>= 0.5` (limiar inicial, não percentual de confiança).
- Validar no MongoDB propriedade, status e versão do resumo antes de retornar.
- Se houver candidatos semânticos válidos, retornar somente esses. Se nenhum passar, preservar o fallback já definido: devolver até 3 resumos encerrados mais recentes do MongoDB, identificados como fallback e sem atribuir score semântico.
- O router pode seguir sem memória quando a lista vier vazia ou a busca estiver indisponível; a falha deve ser observável e não pode expor dados de outro usuário.

## Fronteira entre branches

**Branch `memory`:** contratos e repositórios MongoDB, restauração de histórico, serviço de busca Qdrant, integração de sumarização/indexação no encerramento e contrato da tool para o router.

**Branch `api` (futura):** autenticação e endpoints para iniciar, listar sessões encerradas por título, selecionar/retomar e encerrar conversa. A API passa `user_id` da identidade validada e `conversation_id` selecionado; não envia identidade confiável pelo corpo do app.

## Organização proposta

```text
src/memory/
  contracts.py                 # IDs, mensagens, conversa e resumos
  mongo_repository.py          # histórico, status, lista por usuário e resumo
  message_service.py            # gravação idempotente das mensagens
  enrich_context.py             # novo: retomada MongoDB -> GraphState.messages
  get_summary_context.py        # busca Qdrant e valida payload
  qdrant_summary_indexer.py     # novo: embedding e upsert estável do resumo
  summary_context_service.py    # score, validação Mongo e retorno de até 3
  conversation_lifecycle.py    # novo: reabrir/encerrar e coordenar resumo + índice
  worker/
    summary_prompt.py            # novo: modos initial e incremental
    summarizer_end_conversation.py # LLM, diferença de mensagens e retry do índice
    title_generator.py            # novo: título estruturado com Gemini Flash-Lite
```

O wrapper da tool fica em `src/agents/router/tools/search_conversation_summaries.py`, conforme a convenção do repositório. O código de busca e acesso aos dados continua em `src/memory`.

## Destino dos arquivos existentes

| Arquivo atual | Direção |
|---|---|
| `contracts.py` | Reutilizar; consolidar os três IDs e remover aliases sem uso. |
| `message_service.py` | Reutilizar para gravação idempotente de mensagens finais do usuário e assistente. |
| `mongo_repository.py` | Reutilizar e completar leitura para retomada, reabertura, lista encerrada e gravação de resumo. |
| `get_summary_context.py` | Reutilizar como adapter Qdrant; garantir filtro, limite e score do contrato. |
| `qdrant_summary_indexer.py` | Novo adapter para embedding e upsert de um ponto estável por conversa. |
| `service.py` | Refatorar para busca sob demanda pelo router; preservar fallback recente somente quando não houver resultado semântico válido. |
| `worker/summarizer_end_conversation.py` | Implementar o fluxo com o LLM centralizado: primeiro fechamento resume o histórico; os seguintes atualizam `resumo anterior + mensagens após o marcador`. Versionar, avançar o marcador e fazer upsert Qdrant idempotente. |
| `worker/summary_prompt.py` | Novo prompt com os modos `initial` e `incremental`, usando somente o conteúdo recebido. |
| `run_context_enrichment_node` em `graphs/adapters.py` | Simplificar para chamar o módulo de retomada; não chamar busca semântica. |
| `GraphState` | Manter `messages` como histórico principal; explicitar ação nova/retomada e manter identidade/IDs no request. |

Essa organização é um plano, não uma solicitação para substituir agora todos os arquivos da branch. Antes da implementação, conferir os contratos e testes existentes para evitar duplicar serviços que já atendam ao desenho.

## Ordem de implementação da branch `memory`

1. Fechar contrato de IDs, ação nova/retomada e ownership de estado.
2. Completar repositório MongoDB para carregar, reabrir, listar encerradas e atualizar conversa/resumo.
3. Implementar `enrich_context` para restaurar mensagens na retomada.
4. Refatorar busca semântica para uso sob demanda e conectá-la à tool do router.
5. Fechar o ciclo de resumo incremental, embedding e upsert Qdrant com retry idempotente; em retry, não reaplicar mensagens já incluídas no marcador.
6. Gerar e persistir o título ausente a partir do resumo, sem refazer títulos existentes; indexar o ponto Qdrant com o título salvo.

## Critérios de aceite

- **CA-MEM-01:** em uma conversa nova, o nó `enrich_context` não consulta Qdrant nem carrega mensagens antigas; depois, o router ainda pode chamar a tool se decidir que precisa de memória.
- **CA-MEM-02:** dada uma retomada autorizada, `enrich_context` restaura as mensagens MongoDB em ordem, preserva `message_id` e não duplica a entrada atual.
- **CA-MEM-03:** dado um router que solicita memória, a tool retorna no máximo 3 resumos próprios e encerrados com score mínimo 0.5 e versão válida.
- **CA-MEM-04:** sem candidatos semânticos elegíveis, a tool usa o fallback dos até 3 resumos encerrados mais recentes do MongoDB; com candidatos válidos, não completa a lista com fallback.
- **CA-MEM-05:** ao encerrar, só mensagens posteriores a `summarized_through_message_id` são combinadas com o resumo anterior; na primeira geração usa-se o histórico completo. O novo resumo e marcador ficam no MongoDB e o Qdrant recebe upsert do mesmo `conversation_id`; retry não resume a mesma diferença duas vezes.
- **CA-MEM-06:** ao retomar e encerrar novamente, a conversa mantém o ID e o resumo/ponto vetorial é atualizado.
- **CA-MEM-07:** IDs ou payloads de outra pessoa nunca permitem leitura, alteração ou recuperação de contexto.
- **CA-MEM-08:** o primeiro resumo de uma conversa sem título recebe um título em português gerado por `gemini-2.5-flash-lite`; retomadas preservam o título, e falha de título não impede persistência/indexação do resumo.

## Fora do escopo desta branch

Definir rotas HTTP, autenticação do app, formato da lista visual, UX de seleção e encerramento, e contrato completo entre Spring e FastAPI. Essas decisões entram no planejamento da branch `api`.
