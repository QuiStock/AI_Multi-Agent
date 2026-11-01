# Proposal

## Why

O dev precisa entrar numa tela de observabilidade e explicar um turno: o que demorou, qual modelo falou, quanto custou e se o limite de confiabilidade estourou. Hoje a Visão geral calcula uma parte disso no próprio serviço, a API `/api/v1/observability` responde sem login, e o que o LangSmith mostraria não está coberto aqui.

## What Changes

- Login só da página de observabilidade e da API `/api/v1/observability`, inclusive o laboratório. A API de conversas continua com o JWT atual.
- **BREAKING**: essa API deixa de responder sem a sessão desse login.
- A conta é um e-mail e uma senha conferidos na tabela `super_admin`, no mesmo Postgres de `user_account`. As colunas são `email` e `password`. A senha é bcrypt com prefixo `$2a$`, `$2b$` ou `$2y$`. Esta entrega não cria, não edita e não apaga linhas.
- A Visão geral continua sendo a primeira tela depois do login. Os blocos ficam separados, no espírito de um painel Grafana.
- O serviço calcula, sem usar o LangSmith, os números da aula e os do painel padrão do LangSmith que entraram no escopo: turnos, latência média, p95 nearest-rank, erro, bloqueios separados do erro, tokens, custo, chamadas de modelo, ferramentas e tipos de execução.
- Os SLOs seguem o período e os filtros de usuário/conversa selecionados. O filtro de status não restringe a amostra. A meta de conclusão segue em 99,5% e o limite de latência em p95 de 20 segundos; os limites da aula (8 segundos e 5%) não substituem esses objetivos.
- O custo usa a tabela já codificada: GPT-6 Luna a US$ 0,10 / US$ 0,50 por milhão de tokens, sem cache, e embedding Gemini a US$ 0 ou US$ 0,20 conforme o plano.
- O trace abre dentro da plataforma, com as etapas. A ligação com o LangSmith fica para depois desta cobertura.
- Fora desta entrega: feedback, datasets, playground, cadastro de usuário, texto de prompt na tela, tempo até o primeiro token e nota da resposta.

## Capabilities

### New Capabilities

- `observability-access`: quem entra na página e na API de observabilidade.
- `observability-metrics`: números de confiabilidade e de custo calculados no serviço.
- `trace-inspection`: leitura de um trace e das etapas dentro da plataforma.

### Modified Capabilities

- Nenhuma. Não há spec OpenSpec anterior.

## Impact

- `src/observability/front-observer`, `src/api/routes/observability.py`, `src/api/services/observability_service.py` e `src/observability/metrics.py`.
- Leitura de `super_admin` no Postgres já usado pelas contas. Sem tela de cadastro.
- A API de conversas não muda.
- Nenhuma chamada ao LangSmith nesta entrega. A comparação da senha usa a dependência `bcrypt`.
