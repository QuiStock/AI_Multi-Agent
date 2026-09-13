# Quais perguntas orientarão a especificação SDD do projeto?

## Rodada 1 — Qual é o escopo inicial do sistema?

1. O MVP deve permitir que o funcionário crie solicitações e o gerente aprove ou rejeite, ou continuará apenas consultivo?
2. Quando uma solicitação for aprovada, o sistema apenas registrará a aprovação ou deverá criar efetivamente um pedido ou uma promoção no banco?
3. Um funcionário pertence a apenas uma loja?
4. Um gerente pode administrar várias lojas?
5. Uma loja pode pertencer a somente um gerente regional?
6. A escola aceitará roteador, juiz e compilador na contagem dos cinco agentes ou exigirá cinco agentes especialistas de domínio?

## Rodada 2 — Como funcionarão solicitações e permissões?

1. Quem poderá criar uma solicitação manual: apenas o funcionário, apenas o gerente ou ambos?
2. Loja, produto, tipo de ação, justificativa, quantidade sugerida, percentual de desconto, autor e data serão informações obrigatórias da solicitação?
3. O gerente poderá alterar quantidade, desconto ou justificativa antes de aprovar?
4. O gerente poderá somente aprovar ou rejeitar exatamente o conteúdo recebido?
5. Ao rejeitar uma solicitação, o gerente deverá informar obrigatoriamente um motivo?
6. Depois da aprovação, alguém deverá marcar a ação como em execução ou concluída?
7. O gerente regional será apenas observador ou poderá intervir nas decisões?
8. O gerente regional visualizará métricas e solicitações de todas as lojas sob sua responsabilidade?
9. O gerente regional visualizará dados agregados, detalhes por produto ou ambos?

## Rodada 3 — Qual será o contrato dos dados produzidos pelo ML?

1. O ML classificará cada lote individual, o produto considerando todos os lotes da loja ou ambos?
2. Uma sugestão de promoção será aplicada a um lote específico, a todos os lotes do produto na loja ou conforme indicação do ML?
3. Uma sugestão de pedido referenciará o produto ou SKU mesmo quando a análise tiver partido dos lotes existentes?
4. O resultado do ML deverá conter `loja_id`?
5. O resultado do ML deverá conter `produto_id`?
6. O resultado do ML precisará conter `lote_id` em algum cenário?
7. O resultado do ML deverá conter a classificação `ALTO`, `NORMAL` ou `BAIXO`?
8. O resultado do ML deverá conter a ação `PEDIDO`, `PROMOCAO` ou `NENHUMA`?
9. O resultado do ML deverá conter score ou confiança?
10. O resultado do ML deverá conter um motivo estruturado?
11. O resultado do ML deverá conter o início e o fim do período analisado?
12. O resultado do ML deverá conter a versão do modelo?
13. O resultado do ML deverá conter o identificador da execução?
14. O resultado do ML deverá conter a data de geração?
15. O resultado do ML deverá conter uma data de validade ou indicador de freshness?
16. O ML atualizará os resultados diariamente, semanalmente ou sob demanda?
17. O que deverá acontecer quando uma nova execução do ML mudar a classificação de uma sugestão ainda pendente?
18. Uma sugestão antiga deverá continuar disponível para decisão até o fim de seu período de validade?
19. Uma sugestão criada pelo gerente deverá entrar diretamente na lista de aprovadas?
20. O gerente regional poderá visualizar as decisões e justificativas registradas pelos gerentes?
21. A quantidade sugerida para pedido será expressa em unidades, peso, caixas ou número de lotes?

## Rodada 4 — Como funcionarão autenticação, sessões e memória?

1. O app existente fará login e enviará um token para a API ou a API deverá implementar login e emissão de token?
2. O histórico de chat será privado e acessível somente ao próprio usuário?
3. Por quanto tempo uma conversa inativa deverá permanecer no Redis?
4. O TTL da sessão no Redis deverá ser renovado a cada nova atividade?
5. O que será considerado memória de longo prazo no projeto?
6. As mensagens completas permanecerão somente no Redis?
7. Os resumos estruturados das conversas serão persistidos no PostgreSQL?
8. As decisões comerciais permanecerão separadas da memória do chatbot?
9. O agente poderá recuperar resumos de sessões anteriores do mesmo usuário?
10. Por quanto tempo os resumos duráveis permanecerão armazenados?
11. O chatbot lembrará somente contexto profissional ou também conversas completas anteriores?
12. Quantas conversas anteriores poderão ser recuperadas por sessão?
13. O funcionário poderá consultar somente dados da própria loja?
14. O gerente poderá consultar todos os detalhes da própria loja?
15. O gerente regional poderá consultar métricas, recomendações e justificativas de todas as lojas sob sua responsabilidade?
16. O gerente regional poderá visualizar o nome do gerente responsável por cada decisão?

## Rodada 5 — Qual será o contrato técnico das sessões?

1. Qual tipo de token o app existente enviará: JWT, token opaco ou outro formato?
2. Qual claim ou identificador representará o usuário autenticado?
3. A API consultará cargo, loja e região no PostgreSQL em vez de confiar nesses dados enviados pelo frontend?
4. Um usuário poderá manter várias sessões de chat simultaneamente?
5. O usuário poderá dar um título à conversa?
6. O usuário poderá encerrar uma conversa manualmente?
7. Quantos resumos anteriores o agente deverá recuperar?
8. A quantidade de resumos recuperados será configurável por variável de ambiente?
9. O resumo será atualizado progressivamente durante a conversa?
10. Depois de quantas mensagens o resumo progressivo deverá ser atualizado?
11. Uma versão final do resumo será produzida quando a sessão for encerrada ou expirar?
12. O resumo persistente conterá assuntos, produtos, lojas, períodos, conclusões e pendências da conversa?
13. Quais informações deverão ser proibidas no resumo persistente?
14. O usuário poderá excluir suas próprias sessões e memórias?
15. Um administrador poderá excluir sessões e memórias de outros usuários?
16. O que o Redis deverá armazenar além das mensagens e checkpoints recentes?

## Rodada 6 — Como funcionará o FAQ/RAG no Qdrant?

1. Quais documentos reais formarão a base de conhecimento do FAQ?
2. Os documentos serão globais para todas as lojas ou poderão variar por loja, região ou cargo?
3. Quem poderá cadastrar, atualizar e remover documentos da base?
4. Quais formatos serão aceitos: PDF, Markdown, texto ou outros?
5. Como uma atualização da base será comunicada à API?
6. A verificação de mudança utilizará hash por documento, fingerprint global ou ambos?
7. A reindexação será completa ou incremental por documento e chunk alterado?
8. A nova versão do índice deverá ser criada sem interromper consultas à versão anterior?
9. Como ocorrerá a ativação e o rollback de uma versão do índice?
10. Qual modelo de embedding gratuito será utilizado?
11. O que acontecerá quando o serviço de embedding estiver indisponível?
12. A collection do Qdrant será separada por ambiente, modelo de embedding ou base de conhecimento?
13. Quais metadados cada chunk deverá armazenar para permitir filtros, citações e auditoria?
14. Toda resposta do FAQ deverá retornar arquivo, página e versão da base?
15. Qual relevância mínima será exigida para considerar uma evidência válida?
16. Como será tratada uma pergunta cuja resposta não esteja na base?
17. Como documentos maliciosos ou instruções encontradas no conteúdo recuperado serão neutralizados?

## Rodada 7 — Como serão organizados agentes, estado e validações?

1. Quais responsabilidades exatas pertencem ao roteador?
2. Quais intenções o roteador deverá reconhecer no MVP?
3. O roteador poderá dividir uma mensagem com múltiplas intenções?
4. FAQ e Product Workflow poderão executar em paralelo quando uma mensagem exigir ambos?
5. Quais campos cada agente poderá ler no estado compartilhado?
6. Quais campos cada agente poderá escrever no estado compartilhado?
7. Quais dados serão privados de cada agente e não poderão ser persistidos no estado global?
8. Como os resultados concorrentes serão acumulados sem sobrescrita?
9. Quais evidências estruturadas o FAQ deverá entregar ao juiz?
10. Quais registros estruturados o Product Workflow deverá entregar ao juiz?
11. O juiz validará groundedness, citações, versão dos dados, escopo de acesso e consistência da resposta?
12. O que acontecerá quando o juiz reprovar uma resposta?
13. Será permitida uma tentativa de correção antes da recusa controlada?
14. O compilador poderá apenas combinar resultados já validados?
15. Quais verificações pertencerão ao guardrail de entrada?
16. Quais verificações pertencerão ao guardrail de saída?
17. Qual agente ou node será responsável pela resposta quando a solicitação for ambígua ou estiver fora do escopo?
18. Quais versões de prompt, modelo e ferramenta deverão ser registradas em cada execução?

## Rodada 8 — Quais contratos a API deverá oferecer?

1. Quais endpoints serão necessários para criar, listar, consultar, encerrar e excluir sessões?
2. Qual endpoint receberá mensagens do chatbot?
3. A primeira versão será somente síncrona ou também oferecerá streaming por SSE?
4. Qual será o formato da resposta do chatbot?
5. A resposta deverá separar texto, evidências, dados estruturados, status e identificadores de rastreamento?
6. Quais endpoints permitirão listar recomendações do ML?
7. Quais endpoints permitirão criar sugestões manuais?
8. Quais endpoints permitirão ao gerente editar, aprovar ou recusar sugestões?
9. Como serão listadas as sugestões aprovadas para os funcionários?
10. Quais filtros serão permitidos por loja, produto, origem, status, ação, período e versão do ML?
11. Como funcionará a paginação das listas?
12. Quais operações exigirão chave de idempotência?
13. Como conflitos de atualização concorrente serão detectados?
14. Quais códigos HTTP e contratos de erro serão utilizados?
15. Como a API impedirá acesso a lojas fora do escopo do usuário?
16. Como serão implementados health check, readiness check e versionamento da API?

## Rodada 9 — Como serão modelados recomendações, decisões e auditoria?

1. Recomendações do ML e sugestões humanas utilizarão a mesma entidade?
2. Quais valores de origem serão permitidos: `ML`, `FUNCIONARIO` e `GERENTE`?
3. Quais estados serão permitidos para cada origem?
4. Como uma sugestão criada pelo gerente será marcada como automaticamente aprovada?
5. Uma decisão guardará os valores originais e os valores alterados pelo gerente?
6. Como serão registrados autor, decisor, justificativa e timestamps?
7. Uma sugestão aprovada ou recusada poderá ser alterada posteriormente?
8. Poderão existir várias sugestões pendentes para o mesmo produto e loja?
9. Como sugestões duplicadas serão identificadas?
10. Como uma sugestão será vinculada à execução e à versão do ML que a originou?
11. Como recomendações antigas ainda válidas serão diferenciadas da recomendação mais recente?
12. Quais alterações deverão produzir eventos de auditoria imutáveis?
13. Quem poderá consultar a trilha de auditoria?

## Rodada 10 — Quais integrações MCP e A2A serão demonstradas?

1. A rubrica exige MCP e A2A simultaneamente ou aceita apenas um deles?
2. Qual sistema externo real será integrado ao projeto?
3. O MCP será servidor, cliente ou ambos?
4. Quais recursos ou ferramentas o MCP disponibilizará?
5. As ferramentas MCP serão exclusivamente de leitura no MVP?
6. Como identidade, loja e permissões serão propagadas para uma chamada MCP?
7. Como timeouts, indisponibilidade e respostas inválidas do MCP serão tratados?
8. Qual agente externo participará da demonstração A2A?
9. Quais tarefas poderão ser delegadas ao agente externo?
10. Qual contrato de mensagem, autenticação e correlação será utilizado no A2A?
11. Como o juiz validará informações recebidas de sistemas ou agentes externos?
12. Como a API responderá quando uma integração externa estiver indisponível?

## Rodada 11 — Quais metas de observabilidade, custo e confiabilidade serão adotadas?

1. Quantos usuários ativos semanais serão considerados nos cenários de 100 e 1000 usuários?
2. Quantas sessões por usuário por semana serão assumidas?
3. Quantas mensagens por sessão serão assumidas?
4. Qual será o tamanho médio de entrada e saída em tokens?
5. Qual modelo gratuito ou local será utilizado em cada agente?
6. Como o sistema garantirá que não haja cobrança por API generativa?
7. Quais custos de infraestrutura serão considerados mesmo quando o LLM tiver custo monetário zero?
8. Qual será a fórmula de custo semanal por cenário?
9. Como será calculado o custo por resolução?
10. O que será considerado uma resolução válida?
11. Como será estimado o retorno financeiro por ruptura evitada?
12. Como será estimado o retorno financeiro de uma promoção aprovada?
13. Qual fórmula de ROI será adotada?
14. Qual será a meta de latência p95 entre agentes?
15. Qual será a meta de tempo total p95 por resposta?
16. Qual taxa máxima de erros será aceita?
17. Qual disponibilidade será definida como SLO?
18. Quais métricas, logs e traces serão coletados?
19. Qual solução de observabilidade será utilizada?
20. Como dados sensíveis serão mascarados em logs e traces?

## Rodada 12 — Como será a arquitetura e a operação do sistema?

1. Onde FastAPI, LangGraph, Redis, PostgreSQL, Qdrant e observabilidade serão hospedados?
2. O sistema terá um único processo ou serviços separados?
3. Haverá workers assíncronos para sumarização, indexação e ingestão dos resultados do ML?
4. Como o pipeline de ML publicará uma nova execução para a API?
5. Como serão gerenciados secrets, tokens e chaves de API?
6. Quais são as fronteiras de confiança entre app, API, bancos, modelos e integrações externas?
7. Como serão feitos backup e restauração do PostgreSQL e do Qdrant?
8. O Redis poderá ser perdido sem perda de dados duráveis?
9. Como múltiplas instâncias da API evitarão reindexações simultâneas e decisões concorrentes?
10. Quais ambientes existirão: desenvolvimento, teste, homologação e produção?
11. Qual estratégia de migrations será utilizada para o PostgreSQL?
12. Como alterações incompatíveis no estado LangGraph e nos checkpoints serão migradas?
13. Quais testes unitários, de integração, aceitação, segurança e carga serão obrigatórios?
14. Quais critérios deverão ser atendidos antes de considerar o MVP concluído?
