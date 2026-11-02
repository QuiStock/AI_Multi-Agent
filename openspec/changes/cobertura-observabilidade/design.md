# Design

**Status:** implementação concluída; este documento registra o desenho original. O runtime atual e os limites operacionais estão descritos em `AGENTS.md` e nas specs ativas.

## Contexto na abertura da change

A Visão geral e o Trace Explorer já existiam em `src/observability/front-observer`. Naquele momento a API de observabilidade ainda não exigia a sessão própria; esta change implementou o login e o gate nas rotas. A API de conversas continua usando seu próprio Bearer JWT. `super_admin` é somente lida pelo login de observabilidade. Ver `proposal.md`.

## Goals / Non-Goals

**Goals:**

- Uma sessão própria para a página e para `/api/v1/observability`.
- Completar os blocos e o detalhe do trace com os dados que o serviço já guarda, sem cliente LangSmith.

**Non-Goals:**

- Criar linhas em `super_admin`.
- Alterar a API de conversas.

## Decisions

1. A sessão de observabilidade é um cookie próprio, separado do JWT das conversas. O JWT atual identifica o usuário do chat, não a linha de `super_admin`. Alternativa descartada: reutilizar o JWT e só checar um papel.
2. O login só lê `super_admin`. Se a tabela ou a linha não existir, a entrada é recusada. Este serviço não faz cadastro nem seed. Alternativa descartada: criar a primeira linha na entrega.
3. A senha em `super_admin.password` é bcrypt. A comparação aceita os prefixos `$2a$`, `$2b$` e `$2y$` com `bcrypt.checkpw`. Hash ausente ou inválido recusa a senha. Alternativa descartada: SHA-256 e Argon2id.
4. Os números novos entram em `calculate_metrics` e na Visão geral atual. Chamadas JEV, que usam HTTP direto e não geram spans LangChain, são registradas como spans filhos do nó judge e persistidas junto ao trace do turno. Eventos antigos do JEV continuam legíveis durante a transição. O Qwen é contado pelo model ID dos spans já capturados.
5. O detalhe do trace reaproveita o Trace Explorer. A página lista os spans guardados. Não há chamada externa para montar a árvore.

## Risks / Trade-offs

- [A API passa a exigir sessão] → Publicar a API e a página juntas. Sem a página, o cliente antigo quebra.
- [O hash gravado pode ser `$2b$` mesmo com o padrão `$2a$`] → A comparação aceita os três prefixos bcrypt. Um hash que não é bcrypt recusa a senha.
- [Um span sem tokens não tem custo] → O detalhe mostra nome, duração e status, e deixa tokens em branco.
- [Modelo sem preço na tabela atual] → O custo parcial segue a regra já existente: total incompleto visível, chamada sem preço contada à parte.
- [Projeção semanal confundida por custos operacionais] → Somente custos de uso associados a conversas entram no custo variável; laboratório e indexação ficam visíveis por origem e fora das projeções.

## Migration Plan

1. Publicar a leitura de `super_admin` e a sessão junto com a tela de login.
2. Só então exigir a sessão nas rotas de observabilidade.
3. Rollback: reverter a exigência da sessão e a tela de login no mesmo passo. As métricas novas podem permanecer.

## Open Questions

- Nenhuma. Em 2026-10-27, `public.super_admin` tem `email` e `password`, e a senha é bcrypt.
