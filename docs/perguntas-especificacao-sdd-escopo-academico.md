# Quais decisões ainda precisam ser tomadas para especificar o projeto acadêmico?

## Rodada 1 — Como o projeto será dividido entre os sistemas?

1. A API Java com Spring cuidará dos CRUDs e das regras comerciais enquanto a FastAPI cuidará somente do chatbot e dos agentes?
2. A FastAPI consultará os dados comerciais pela API Spring ou diretamente no PostgreSQL?
3. Qual identificador de usuário será recebido no token gerado pelo aplicativo?
4. Qual sistema validará esse token?
5. Cargo, loja e região serão obtidos do token ou consultados em uma fonte confiável?
6. Quais componentes precisarão estar operacionais na apresentação e quais poderão usar dados simulados?

## Rodada 2 — Como serão representados produtos, métricas e sugestões?

1. A quantidade sugerida para pedido será expressa em unidades, peso, caixas ou número de lotes?
2. Quais métricas serão usadas pelo ML para classificar um produto como `ALTO`, `NORMAL` ou `BAIXO`?
3. Quem definirá os limites entre as três classificações?
4. Como o resultado semanal do ML chegará ao PostgreSQL?
5. Qual será o período de validade de uma recomendação?
6. Como uma recomendação atual será diferenciada de uma recomendação antiga ainda válida?
7. Poderão existir várias sugestões pendentes para o mesmo produto e loja?
8. Uma decisão do gerente guardará os valores originais, os valores alterados e a justificativa?

## Rodada 3 — Como funcionarão os cinco agentes e os guardrails?

1. Quais intenções o roteador reconhecerá no MVP?
2. O FAQ responderá exclusivamente com evidências recuperadas dos documentos?
3. O Product Workflow Agent será exclusivamente de leitura no MVP?
4. Quais evidências estruturadas cada agente especialista enviará ao juiz?
5. Quais verificações mínimas o juiz realizará antes de aprovar uma resposta?
6. O que acontecerá quando o juiz reprovar uma resposta?
7. O compilador somente combinará respostas aprovadas pelo juiz?
8. FAQ e Product Workflow poderão ser acionados juntos na mesma pergunta?
9. Quais verificações mínimas pertencerão aos guardrails de entrada e saída?

## Rodada 4 — Como MongoDB, Redis e Qdrant serão usados localmente?

1. O MongoDB armazenará mensagens completas, resumos ou ambos para atender à interação conversacional obrigatória?
2. Quantos resumos anteriores serão carregados como memória de longo prazo?
3. Quando o resumo de uma conversa será criado ou atualizado?
4. Quais informações poderão ser persistidas no resumo e quais deverão ser removidas?
5. O usuário poderá excluir suas próprias conversas e memórias?
6. O Redis manterá sessões e checkpoints recentes com TTL de 72 horas?
7. Qual tarefa assíncrona será demonstrada obrigatoriamente por uma fila Redis?
8. O Qdrant será executado localmente e usado apenas para os vetores do FAQ?
9. Qual modelo gratuito ou local será usado para gerar embeddings?
10. Como o sistema detectará documentos alterados e reindexará somente o necessário sem perder o índice anterior?

## Rodada 5 — Quais contratos mínimos a FastAPI e as integrações oferecerão?

1. Quais endpoints criarão sessões, receberão mensagens, listarão conversas e excluirão memórias?
2. Qual estrutura de texto, fontes, dados, status e `trace_id` será devolvida pelo chatbot?
3. A primeira versão será síncrona ou terá streaming?
4. Quais limites de tamanho de mensagem e frequência serão aplicados?
5. Qual documento real será consumido como fonte externa do RAG?
6. O MCP local oferecerá consultas somente leitura de métricas e recomendações?
7. Qual serviço ou agente local participará da demonstração A2A?
8. Qual tarefa simples será executada via A2A e como sua resposta será validada?

## Rodada 6 — Como os requisitos de Modelagem de Dados e BI serão atendidos?

1. Quais entidades, PKs, FKs e cardinalidades formarão o novo modelo PostgreSQL em 3FN?
2. Como serão gerados pelo menos 500 registros verossímeis?
3. Qual fonte será tratada como banco legado na integração RPA?
4. Como a RPA registrará sucesso e falhas na movimentação dos dados?
5. Quais fatos, dimensões e KPIs formarão o Data Mart?
6. Quais views analíticas demonstrarão CTEs e window functions?
7. Quais duas regras de negócio serão implementadas como functions e quais duas como procedures?
8. Quais duas tabelas terão triggers completas de auditoria?
9. Quais consultas serão comparadas com `EXPLAIN ANALYZE` antes e depois dos índices?

## Rodada 7 — Como observabilidade, custos e execução local serão demonstrados?

1. Quantas sessões e mensagens por usuário serão assumidas nos cenários de 100 e 1000 usuários semanais?
2. Qual modelo gratuito ou local será usado por cada agente?
3. Como o sistema impedirá cobranças acidentais de APIs generativas?
4. O que será considerado uma resolução bem-sucedida e como será calculado seu custo?
5. Como será estimado o ROI de rupturas evitadas e promoções aprovadas?
6. Quais metas simples serão adotadas para latência total, latência entre agentes e índice de erros?
7. Quais métricas e logs serão coletados e como dados sensíveis serão mascarados?
8. Quais serviços serão executados com Docker Compose local e qual parte mínima será demonstrada em cloud?

## Rodada 8 — Quais evidências definirão a conclusão do MVP?

1. Quais casos de uso serão ligados aos requisitos funcionais e usados nos dois diagramas de atividades?
2. Quais testes comprovarão isolamento entre usuários, cargos, lojas e sessões?
3. Quais testes comprovarão memória no MongoDB, fila no Redis e reindexação no Qdrant?
4. Quais testes comprovarão RAG com fontes, juiz, guardrails, MCP e A2A?
5. Qual carga será usada para medir latência e índice de erros?
6. Quais diagramas, relatórios, links e evidências serão reunidos no documento final de entregas?
