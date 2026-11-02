# Proposal

**Status:** implementado; proposta histórica. O contrato atual está nas specs delta deste change, em `AGENTS.md` e no runtime.

## Why

O dev precisa entrar numa tela de observabilidade e explicar um turno: o que demorou, qual modelo falou, quanto custou e se o limite de confiabilidade estourou. Antes desta change, a Visão geral calculava apenas parte das métricas e a API `/api/v1/observability` não exigia login próprio. Esta change implementou a sessão; a plataforma não usa LangSmith para calcular essas métricas.

## Resultado implementado

- A página e todas as rotas de /api/v1/observability, incluindo laboratório e feed ao vivo, exigem sessão própria. O acesso de conversa permanece com seu JWT Bearer.
- O login consulta super_admin (email, password) e compara bcrypt; não cria nem altera linhas.
- A Visão geral e o Trace Explorer usam dados do próprio serviço, sem LangSmith.
- A API, os cards de SLO e o banner usam a mesma meta: 95% de turnos sem erro (até 5% de erro) e p95 de latência até 20 segundos.
- Custos de chamadas JEV são estimados por tokens de entrada registrados; chamadas sem uso/preço aparecem como incompletas.
- O Trace Explorer mostra os spans e logs armazenados. A Visão geral não exibe etapas do grafo.
- Custos variáveis de conversa sustentam custo por conversa e projeções; laboratório e indexação aparecem separados.

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
