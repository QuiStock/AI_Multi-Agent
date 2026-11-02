# Contrato executável A2A

> **Fora do escopo atual (decisão de 2026-11-02):** MCP e A2A não serão implementados nesta entrega. Este arquivo é registro histórico de propostas/decisões anteriores; seus requisitos, aprovações e fluxos não são autorização nem instruções para o runtime.

## Fluxo

```text
Cliente A2A → AgentCard Quistock → POST /a2a/message:send
            → credencial do serviço + store_id + ID do usuário externo
            → validação da loja ativa no PostgreSQL (somente SELECT)
            → gerente A2A da loja, sem conta humana Quistock
            → contextId isolado por cliente, loja e usuário externo
            → ConversationService → mesmo grafo das rotas normais

router → faq | product_workflow | external_a2a
                             external_a2a → mock | peer REST configurado
                                         → compiler → judge → guardrail → memória
```

`EventQueue` é um mecanismo interno do SDK para entregar eventos. Neste
contrato síncrono, uma requisição retorna diretamente uma `Message`; não há
Task, Redis ou fila adicional para A2A. O `contextId` agrupa mensagens, e o
checkpointer/memória da conversa continua sendo responsabilidade do Quistock.

## Contratos

| Item | Contrato |
|---|---|
| Descoberta | `GET /.well-known/agent-card.json` publica interface `HTTP+JSON` 1.0 e skills `faq`, `product_flow` e `truck_information`, sem segredos. |
| Entrada | `POST /a2a/message:send` aceita `SendMessageRequest` com `Message` `ROLE_USER` e apenas partes de texto, até 4.000 caracteres. Retorna `SendMessageResponse.message`. |
| Autenticação | `Authorization: Bearer <A2A_INBOUND_SERVICE_TOKEN>`, `X-Quistock-Store-Id: <store_id>` e `X-External-User-Id: <id estável>` são obrigatórios. O token é vinculado a uma única loja em `A2A_INBOUND_STORE_ID`; o header deve coincidir. O sistema cliente autentica seu usuário, e o Quistock autentica o cliente. |
| Loja e papel | Um `SELECT` confirma que `store.id` existe e está `ACTIVE`. O Quistock atribui `role_id=2` ao usuário externo apenas nesse contexto. Não consulta nem cria `user_account`/`user_store`. O Product Workflow A2A filtra `s.store_id` em cada busca e detalhe, mantendo a visibilidade `SENT_TO_MANAGER`; a rota normal conserva o filtro por email e vínculo com a loja. |
| Isolamento | A identidade interna e o ID da conversa são derivados com HMAC de `client_id`, `store_id`, usuário externo e `contextId`. Um `contextId` igual de outra loja ou pessoa não acessa a conversa original. |
| Idempotência | `messageId` por cliente, loja, pessoa e contexto produz `request_id` estável. A resposta é armazenada em MongoDB. Repetição idêntica retorna a resposta; conteúdo diferente ou execução simultânea recebe 409. |
| Saída | O router pode escolher `external_a2a` apenas para `truck_info_agent/truck_specs`. Mock local é o padrão de desenvolvimento. Em `A2A_TRUCK_MODE=remote`, o cliente lê o card configurado, valida a interface e a skill, e envia `SendMessage` ao endpoint fixo. |
| Tempo limite | `A2A_TIMEOUT_SECONDS=8` limita cada chamada HTTP ao peer. Falha ou Task não suportada gera resposta controlada. A execução local do grafo ainda não tem deadline rígido próprio. |
| Rastreio | `request_id` deriva do `messageId`; o mesmo ID é `trace_id`. O adaptador registra rota, status e contagem de evidências, sem token. |

## Regra do juiz para A2A

A resposta do peer é registrada como `Evidence(source_type=a2a_agent)` com
`trust_level=peer_assertion`. Essa evidência prova **o que o peer respondeu**,
mas não prova que a informação técnica sobre caminhões seja verdadeira. O
compiler precisa atribuir a resposta ao sistema externo; no mock, também
precisa dizer que é uma simulação. O juiz continua verificando citação,
consistência e atribuição. A exigência anterior de fonte original verificável
fica substituída para este primeiro ciclo. Quando o peer definitivo existir,
o contrato de verificação factual deve ser decidido com base no seu retorno.

## Configuração

```dotenv
A2A_PUBLIC_URL=http://localhost:8000/a2a
A2A_INBOUND_CLIENT_ID=trusted_a2a_client
A2A_INBOUND_SERVICE_TOKEN=<segredo do cliente autorizado>
A2A_INBOUND_STORE_ID=<id da loja ativa no PostgreSQL autorizado para esse token>
A2A_CONTEXT_SECRET=<segredo para isolamento de contextId>
A2A_TRUCK_MODE=mock
A2A_TIMEOUT_SECONDS=8

# Para produção, após registrar o peer definitivo:
A2A_TRUCK_MODE=remote
A2A_TRUCK_CARD_URL=https://peer.example/.well-known/agent-card.json
A2A_TRUCK_ENDPOINT_URL=https://peer.example/a2a
A2A_TRUCK_SERVICE_TOKEN=<credencial do Quistock no peer>
```

O cliente não envia token humano Quistock. O card e a URL do endpoint são
configurados pela operação, nunca produzidos pelo router. Em produção, o mock
é recusado e o transporte remoto exige HTTPS.

## Pendências para produção

- Definir com o dono do sistema externo token, card e política para fontes reais.
- Para múltiplos clientes ou lojas, substituir a configuração única por um
  registro de credenciais vinculadas a cada loja, sem aceitar `store_id` livre.
- Substituir `MemorySaver` local por checkpoint compartilhado antes de
  distribuir a API em vários workers, ou fixar afinidade e recuperação.
- Definir limite de duração do grafo e suporte a `Task` se o peer definitivo
  precisar de operação longa.
- O extra de múltiplos peers requer registro autorizado de skills, atualização
  do router e validação da escolha; não há URL livre vinda do modelo.
