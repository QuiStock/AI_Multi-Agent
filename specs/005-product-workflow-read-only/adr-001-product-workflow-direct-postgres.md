# ADR-001: Product Workflow com leitura direta do PostgreSQL

**Status**: Accepted

**Date**: 2026-10-03

## Contexto

O Product Workflow precisa consultar `suggestion`, produto, lote e triagem para
responder ao chatbot. A decisão desta rodada é que
a API FastAPI de IA fará essas leituras diretamente no PostgreSQL comercial,
sem provider HTTP/Spring intermediário.

## Decisão

- A FastAPI usa o pool PostgreSQL já criado para autenticação.
- O Product Workflow usa uma credencial configurada para leitura e consultas
  parametrizadas predefinidas.
- O LLM não recebe SQL nem conexão com o banco. Os argumentos das tools são
  filtros tipados e limitados.
- O escopo é aplicado no SQL por `user_account.email`, `user_account.role_id`
  e associação ativa em `user_store`; `store_id` não é aceito como autorização
  enviada pelo cliente ou pelo modelo.
- As consultas leem `suggestion`, `product`, `category`, `store`, `batch`,
  `suggestion_triage`, `suggestion_log`, `user_account` e `user_store`.
  `suggestion_log` é usado somente para excluir sugestões `EXPIRED`;
  `suggestion_decision` não é consultada pelas tools ativas. `MONITOR` não
  entra nas consultas comerciais.
- Spring continua proprietária das escritas e dos CRUDs comerciais. A FastAPI
  não executa `INSERT`, `UPDATE`, `DELETE`, procedures comerciais ou transações
  de mutação.
- Cada linha lida recebe identificadores estáveis de evidência e fonte, com o
  conteúdo da própria linha serializado para o juiz.

## Segurança e operação

- `statement_timeout` é configurado por conexão antes da query.
- Limite de linhas e ordenação são definidos no código; não são produzidos
  pelo modelo.
- A credencial deve receber somente `CONNECT`, `USAGE` nos schemas necessários
  e `SELECT` nas tabelas de leitura.
- A evidência final de produção deve provar que a mesma credencial falha em
  `INSERT`, `UPDATE` e `DELETE`.
- Erro ou timeout do PostgreSQL resulta em indisponibilidade controlada, sem
  resposta factual inventada.

## Consequências

Ganhamos uma implementação direta e simples para o MVP, sem manter um DTO ou
adapter HTTP intermediário. Em contrapartida, a FastAPI passa a depender da
disponibilidade, compatibilidade de schema e grants do PostgreSQL comercial.
Mudanças nas tabelas precisam preservar as queries ou atualizar este ADR,
os modelos e os testes de integração.

## Alternativa rejeitada

Um provider HTTP da API Spring foi rejeitado para esta entrega por adicionar
uma fronteira de contrato que não é necessária ao recorte atual. Essa
alternativa pode ser reconsiderada caso a operação futura exija isolamento
de banco entre serviços.
