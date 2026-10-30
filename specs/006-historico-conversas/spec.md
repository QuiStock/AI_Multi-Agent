# Histórico completo de conversas

Status: API implementada na branch `refactor`; integração da tela pendente no aplicativo.

## Requisitos

- **RF-HIST-001:** `GET /api/v1/conversations/{conversation_id}/messages` devolve todas as mensagens persistidas no MongoDB para uma conversa `active` ou `ended`, na ordem do array `messages`, junto com ID, título e status.
- **RF-HIST-002:** A rota usa o JWT atual e procura a conversa pelo ID e pelo email do principal autenticado. Conversa inexistente, de outra pessoa ou em exclusão retorna 404.
- **RF-HIST-003:** Abrir o histórico não altera o status nem chama o grafo. Uma conversa encerrada só é retomada pelo fluxo existente ao enviar uma nova mensagem.
- **RF-HIST-004:** Mensagens novas são acrescentadas ao documento existente. Após um POST de mensagem bem-sucedido, o app sempre chama o GET do histórico e substitui a lista exibida pela lista completa retornada. Enquanto o GET não concluir, a lista anterior permanece na tela; falha na leitura não a apaga.

## Contrato

Resposta 200: `conversation_id`, `title`, `status` (`active` ou `ended`) e `messages`, cada uma com `message_id`, `role` (`user` ou `assistant`), `content` e `created_at` com timezone. A rota não expõe metadados internos dos agentes. JWT inválido recebe 401; indisponibilidade do MongoDB recebe 503.

## Critérios de aceite

- **CA-HIST-001:** Ao abrir uma conversa ativa ou encerrada, o app recebe todas as mensagens na ordem gravada, inclusive quando duas têm timestamps iguais.
- **CA-HIST-002:** Outro usuário não consegue obter o histórico pelo ID da conversa.
- **CA-HIST-003:** Após o envio de uma nova mensagem, o app chama o GET e exibe as mensagens anteriores mais o novo par, sem duplicatas; a abertura de conversa encerrada não a reativa.
