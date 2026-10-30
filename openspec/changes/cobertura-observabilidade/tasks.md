# Tasks

## 1. Acesso

- [x] 1.1 Conferir no Postgres os nomes reais das colunas de e-mail e do segredo em `super_admin` e anotar esses nomes neste change. Verificar que a anotação cita a tabela e as duas colunas. Colunas: `email` e `password`.
- [ ] 1.2 Exigir sessão de observabilidade na página e em `/api/v1/observability`, inclusive no laboratório, sem mudar a API de conversas. Verificar com teste: chamada sem sessão é recusada, e uma rota de conversa com JWT segue aceita.
- [x] 1.3 Atualizar `src/observability/AGENTS.md` e `src/api/AGENTS.md` com essa sessão. Verificar que os dois textos deixam de dizer que o router de observabilidade não tem controle de acesso.
- [x] 1.4 Comparar a senha com bcrypt (`$2a$`, `$2b$`, `$2y$`), fórmula validada pelo tech manager. Verificar com teste de acerto e de recusa.

## 2. Métricas

- [x] 2.1 Calcular no serviço média, p95 nearest-rank com limite de 20 segundos, erro só por exceção, bloqueios à parte, tokens, custo pela tabela atual, chamadas de modelo, fallbacks, agregados por modelo, por rota, por ferramenta e por tipo de execução a partir dos spans. Verificar com testes unitários desses casos, inclusive bloqueio que não entra no erro.
- [x] 2.2 Manter o banner de conclusão em 99,5% na janela de 28 dias. Verificar no payload da Visão geral que o limite de p95 é 20 segundos e que o limite de 8 segundos e o de 5% não substituem o banner.
- [ ] 2.3 Separar na Visão geral os blocos pedidos, sem texto de prompt, sem tempo até o primeiro token e sem nota da resposta. Verificar na página que cada bloco tem um título próprio.

## 3. Traces

- [ ] 3.1 Mostrar no Trace Explorer cada span com nome, duração e status, e tokens e custo só quando existirem. Verificar com um trace de dois spans, um deles sem tokens.

## 4. Integração

- [x] 4.1 Com sessão válida, a Visão geral devolve os grupos de métricas e o detalhe de um trace. Sem sessão, os dois ficam recusados. Verificar com um teste de API cobrindo os dois casos.

## Workflow follow-up

- Criar o card no Jira só depois que o tech manager aprovar o rascunho.
- Arquivar este change depois que o tech manager aceitar a entrega.
