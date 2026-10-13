# Histórico completo de conversas

Status: implementado na branch `refactor`.

## Requisitos

- **RF-HIST-001:** `GET /api/v1/conversations/{conversation_id}/messages` devolve todas as mensagens persistidas no MongoDB para uma conversa `active` ou `ended`, na ordem do array `messages`, junto com ID, título e status.
- **RF-HIST-002:** A rota usa o JWT atual e procura a conversa pelo ID e pelo email do principal autenticado. Conversa inexistente, de outra pessoa ou em exclusão retorna 404.
- **RF-HIST-003:** Abrir o histórico não altera o status nem chama o grafo. Uma conversa encerrada só é retomada pelo fluxo existente ao enviar uma nova mensagem.
- **RF-HIST-004:** Mensagens novas são acrescentadas ao documento existente. O app mantém as anteriores na tela e acrescenta o novo par de mensagens, ou relê o histórico após o envio.

## Contrato

Resposta 200: `conversation_id`, `title`, `status` (`active` ou `ended`) e `messages`, cada uma com `message_id`, `role` (`user` ou `assistant`), `content` e `created_at` com timezone. A rota não expõe metadados internos dos agentes. JWT inválido recebe 401; indisponibilidade do MongoDB recebe 503.

## Critérios de aceite

- **CA-HIST-001:** Ao abrir uma conversa ativa ou encerrada, o app recebe todas as mensagens na ordem gravada, inclusive quando duas têm timestamps iguais.
- **CA-HIST-002:** Outro usuário não consegue obter o histórico pelo ID da conversa.
- **CA-HIST-003:** Após o envio de uma nova mensagem, uma nova leitura retorna também todas as mensagens anteriores; a abertura de conversa encerrada não a reativa.
