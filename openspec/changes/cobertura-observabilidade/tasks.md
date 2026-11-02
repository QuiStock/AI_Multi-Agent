# Tasks

## 1. Acesso

- [x] 1.1 Conferir no Postgres os nomes reais das colunas de e-mail e do segredo em `super_admin` e anotar esses nomes neste change. Verificar que a anotação cita a tabela e as duas colunas. Colunas: `email` e `password`.
- [x] 1.2 Exigir sessão de observabilidade na página e em `/api/v1/observability`, inclusive no laboratório e feed ao vivo, sem mudar a API de conversas. Verificar com testes: chamada sem sessão é recusada e o CORS não alcança as rotas de conversa.
- [x] 1.3 Atualizar o `AGENTS.md` da raiz com a sessão própria da observabilidade e retirar a afirmação de que o router não tem controle de acesso. O repositório mantém um único `AGENTS.md`.
- [x] 1.4 Comparar a senha com bcrypt (`$2a$`, `$2b$`, `$2y$`), fórmula validada pelo tech manager. Verificar com teste de acerto e de recusa.

## 2. Métricas

- [x] 2.1 Calcular no serviço média, p95 nearest-rank com limite de 20 segundos, erro só por exceção, tokens, custo pela tabela de preços, chamadas de modelo (incluindo uso e custo do JEV), chamadas Qwen como fallback, agregados por modelo, rota, ferramenta e tipo de execução. Verificar cálculos e sinais incompletos.
- [x] 2.2 Fazer os SLOs seguirem período, usuário, conversa e ambiente selecionados, sem aplicar o filtro de status; usar meta de conclusão e sucesso por modelo de 95% e latência p95 de 20 segundos. Verificar que a resposta registra o intervalo usado.
- [x] 2.3 Alinhar os blocos da Visão geral com métricas calculáveis: adicionar board e séries diárias; considerar resolução todo turno concluído sem erro; calcular ROI usando retorno e custo do período selecionado; apresentar um único custo por resolução e o custo médio por conversa; projetar cinco conversas por usuário/semana para 100/1.000 usuários com base móvel de até 30 dias, independente dos filtros da tela; manter laboratório e indexação separados; explicar chamadas incompletas por ausência de uso, preço ou ambos.

## 3. Traces

- [x] 3.1 Mostrar no Trace Explorer cada span e chamada JEV associada com nome/origem, duração e status, e tokens e custo só quando existirem. O JEV é um span persistido junto ao trace; eventos antigos continuam legíveis durante a transição.

## 4. Integração

- [x] 4.1 Com sessão válida, a Visão geral devolve os grupos de métricas e o detalhe de um trace. Sem sessão, os dois ficam recusados. Verificar com um teste de API cobrindo os dois casos.

## Workflow follow-up

- Criar o card no Jira só depois que o tech manager aprovar o rascunho.
- Arquivar este change depois que o tech manager aceitar a entrega.
