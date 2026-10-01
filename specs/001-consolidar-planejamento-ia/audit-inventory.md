# Inventário da auditoria do planejamento de IA

Feature 001-consolidar-planejamento-ia; revisão 2026-09-30. Escopo: repositórios AI_Multi-Agent e Quistock, fontes ligadas ao serviço IA, domínio, dados, integrações, arquitetura e rubrica. Paths do AI repo são relativos à raiz; paths Quistock usam Quistock:. Status únicos: confirmado, implementado, proposto, aberto, divergente; implementação e decisão são dimensões distintas.

## Limites e exclusões

Inspeção estática, sem executar testes de aplicação, serviços ou demonstrações. Nenhum segredo foi aberto. Excluídos: .env/segredos, caches, tmp/.tmp, ambientes virtuais, dependências vendorizadas e gerados. A divergência documental inicialmente encontrada entre AGENTS.md e o adapter FAQ foi corrigida e registrada como AUD-018.

## Catálogo de fontes

| Grupo | Paths/catalogação |
|---|---|
| AI-Multi-Agent: decisão | specs/001-consolidar-planejamento-ia/{spec,plan,research,data-model,quickstart,tasks}.md; contracts/audit-inventory.md; checklists/requirements.md; .specify/feature.json; .specify/memory/constitution.md; .agents/skills; AGENTS.md |
| AI-Multi-Agent: runtime/config | src/{main.py,api,graphs,agents,guardrails,memory,observability,config.py,data/metadata.json}; pyproject.toml; uv.lock; makefile; scripts/index_faq.py; .gitignore |
| AI-Multi-Agent: evidência/docs | tests/ e tests/integration/ (API, graph, agents, RAG, guardrails, memória, workers); docs/planejamento-multiagente-fastapi.md; docs/planejamento-memory.md; docs/perguntas-especificacao-sdd*.md; README.md |
| Quistock: regras/contexto | Quistock:docs/sdd/{README,project-context,academic-constraints,team-and-responsibilities}.md; adr-grafo-modularizado.md; adr-memoria-conversacional.md; specs/{triagem-de-sugestoes,memoria-conversacional}.md |
| Quistock: snapshot IA | Quistock:ai-service/app/agents/{registry,factory,tool_registry}.py; agents/{router,faq_rag,product_workflow,evidence_judge,response_compiler}/executor.py; observability/{audit,metrics,traces}.py. Snapshot/skeleton não substitui runtime deste repo. |
| Quistock: dados | Quistock:modelagem.dbml; docs/modelagem/{quistock-v1,quistock-dbdiagram,quistock-dbdiagram-en}.dbml; quistock-updated.sql; quistock-etl-star.sql; dataload-{oficial,500,1000}.sql; sync-regional-manager-event.sql; rpa-manager-region-updated.sql. Pertinência: modelos, ETL/cargas, loja e integração. Variantes não declaradas canônicas/intercambiáveis. |

## Inventário

| item_id | title | status | current_state | target_state | source_refs | evidence_refs | impact | next_action |
|---|---|---|---|---|---|---|---|---|
| AUD-001 | AI specs como fonte ativa de decisões | confirmado | Spec Kit coexiste com docs históricos. | AI specs governam serviço; Quistock SDD é contexto interdisciplinar. | specs/001-consolidar-planejamento-ia/research.md Decision 1; Quistock:docs/sdd/README.md | .specify/feature.json e specs da feature. | Governança | Manter novas decisões no fluxo Spec Kit. |
| AUD-002 | Processo e estados | confirmado | Cinco status e ciclo documentados. | Rastrear decisão, evidência e implementação separadamente. | specs/001-consolidar-planejamento-ia/spec.md FR-001..010; specs/001-consolidar-planejamento-ia/contracts/audit-inventory.md | Contrato define status/campos. | Todas as features | Reutilizar convenção. |
| AUD-003 | API e grafo | implementado | FastAPI expõe rotas; grafo injeta FAQ, router, compiler, judge, guardrails e memória. | Distinguir capacidades ativas das planejadas. | AGENTS.md; src/main.py; src/api/dependencies.py; src/graphs/agent_graph.py | tests/test_conversation_api.py; tests/test_agent_graph.py; tests/test_health_api.py | API/orquestração | Mudanças via spec/testes. |
| AUD-004 | FAQ RAG/ingestão | implementado | Executor, Qdrant, ferramenta, readers, indexação e evidências presentes. | Respostas fundamentadas/citadas e guardrails. | src/agents/faq; src/graphs/adapters.py; src/guardrails | tests/test_faq_tools.py; tests/test_faq_ingestion.py; tests/test_rag_evaluation.py; tests/integration/test_rag_pipeline.py; tests/integration/test_faq_ingestion_pipeline.py | RAG/qualidade | Preservar avaliação nas mudanças. |
| AUD-005 | Judge/compiler/guardrails | implementado | Componentes usados no fluxo; FAQ requer evidências e saída validada. | Conter respostas sem suporte. | src/agents/{judge,compiler}; src/guardrails | tests/test_judge_executor.py; tests/test_compiler.py; tests/test_input_guardrail.py; tests/test_output_guardrail.py; tests/integration/test_judge_graph_integration.py | Segurança | Não presumir prontidão produtiva. |
| AUD-006 | Memória conversacional | implementado | Mongo, mensagem, lifecycle, checkpointer local e sumarização presentes. | Seguir ADR/spec com identidade e lifecycle. | src/memory; src/api/services; Quistock:docs/sdd/adr-memoria-conversacional.md; Quistock:docs/sdd/specs/memoria-conversacional.md | tests/test_graph_memory_persistence.py; tests/integration/test_memory_mongo_repository.py; tests/test_memory_summary_context.py; tests/test_summary_jobs.py | Continuidade/privacidade | Rever frente a decisões de identidade/deploy. |
| AUD-007 | Busca semântica/fallback | implementado | Qdrant/fallback existem; serviço de memória do router é opcional. | Contexto isolado e fallback previsível. | src/memory/{get_summary_context,service,qdrant_summary_indexer}.py; src/agents/router; AGENTS.md | tests/test_memory_summary_context.py; tests/test_qdrant_summary_indexer.py; tests/test_router_memory_tool.py; tests/test_router_graph.py | Relevância/isolamento | Decidir ativação de runtime. |
| AUD-008 | Jobs de resumo Redis | implementado | Publisher, worker e repository existem; encerramento publica job. | Processamento recuperável e observável. | src/memory/summary_queue.py; src/memory/summary_job_repository.py; src/memory/summary_jobs.py; src/memory/worker/; Quistock:docs/sdd/adr-memoria-conversacional.md; Quistock:docs/sdd/specs/memoria-conversacional.md | tests/test_summary_job_worker.py; tests/test_summary_jobs.py; tests/test_memory_summary_repository.py | Consistência/latência | Resolver operação/retry (AUD-016). |
| AUD-009 | Autenticação/identidade API | confirmado | Recebe user_id em body/query; inspeção não encontrou validação token. Filtrar por user_id não autentica o cliente. | Identidade/escopo por credencial validada. | AGENTS.md seção 6, Identidade e dados comerciais; specs/001-consolidar-planejamento-ia/research.md; Quistock:docs/sdd/project-context.md | src/api/schemas/conversation.py; src/api/dependencies.py; src/api/routes/conversation_list.py; tests/test_conversation_api.py; tests/test_conversation_list_api.py | Segurança | Spec completa após fechar claims/fronteira (AUD-015). |
| AUD-010 | Agente product_workflow | confirmado | Papel no tipo de rota, mas ausente de src/agents/registry.py e não injetado por get_graph. | Consulta read-only autorizada; sem operação comercial. | AGENTS.md; Quistock:docs/sdd/specs/triagem-de-sugestoes.md; Quistock:docs/sdd/academic-constraints.md | src/agents/registry.py; src/api/dependencies.py; Quistock:ai-service/app/agents/product_workflow/executor.py não comprova runtime | Domínio/dados | Spec após contrato de dados/identidade. |
| AUD-011 | MCP/A2A | confirmado | Não há integração ativa identificada em src; roadmap acadêmico futuro. | Escopo, tools, segurança, boundary e evidência em spec. | AGENTS.md; Quistock:docs/sdd/academic-constraints.md; docs/planejamento-multiagente-fastapi.md | Inspeção src/registry/grafo | Rubrica | Selecionar futuro ciclo. |
| AUD-012 | Observabilidade | confirmado | src/observability/audit.py, metrics.py, traces.py são placeholders. | SRE/auditoria com privacidade. | AGENTS.md; Quistock:docs/sdd/academic-constraints.md; docs/planejamento-multiagente-fastapi.md | Conteúdo dos três módulos | SRE/privacidade | Especificar sinais, retenção, redaction. |
| AUD-013 | Regras workflow Quistock | confirmado | Triagem especifica ML/MONITO, janela 30d, validade <=15d, papéis e não execução comercial; runtime IA não implementa workflow. | IA consulta/explica; ML classifica, pessoa decide. | Quistock:docs/sdd/specs/triagem-de-sugestoes.md RF-SUG-001..012/CA; Quistock:docs/sdd/project-context.md | Quistock:ai-service/app/agents/product_workflow/executor.py não prova integração no runtime atual. | Semântica/risco comercial | Referenciar na futura spec; manter abertos. |
| AUD-014 | Contrato canônico de dados | aberto | Múltiplos DBML/SQL/ETL/cargas; contrato consumível canônico não identificado. | Contrato read-only versionado, owner, proveniência, loja e segurança. | Quistock:modelagem.dbml; Quistock:docs/modelagem/quistock-v1.dbml; Quistock:docs/modelagem/quistock-dbdiagram.dbml; Quistock:docs/modelagem/quistock-dbdiagram-en.dbml; Quistock:quistock-updated.sql; Quistock:quistock-etl-star.sql; Quistock:docs/sdd/specs/triagem-de-sugestoes.md | Arquivos existem, versão/propósito não resolvidos pelo nome. | product_workflow | Owners elegem contrato; bloqueia consultas. |
| AUD-015 | Fronteira API comercial/FastAPI | aberto | Docs/serviços separados; contrato ponta a ponta identidade/payload não localizado. | Responsabilidades e fronteiras compatíveis. | docs/planejamento-multiagente-fastapi.md; Quistock:docs/sdd/project-context.md; Quistock:docs/sdd/academic-constraints.md | src/main.py; src/api/routes/; Quistock:ai-service/app/; sem contrato validado no recorte. | Auth/API/deploy | ADR+contrato conjunto; bloqueia AUD-009/010 em produção. |
| AUD-016 | Operação de infraestrutura | aberto | Mongo/Qdrant/Redis configurados; deploy, retry, retenção, backup, SLO não verificados/decididos. | Ambiente seguro, reproduzível, mensurável. | src/config.py; src/api/dependencies.py; src/memory/; Quistock:docs/sdd/academic-constraints.md; docs/planejamento-memory.md | Testes não executados e não provam deploy. | SRE/dados | Definir ambiente, secrets, retry/DLQ, retenção, backup. |
| AUD-017 | Fronteira de autoridade entre SDDs | confirmado | Quistock SDD governa as especificações do produto Quistock; decisão ativa estabelece AI specs para o serviço de IA. Escopos complementares, não contraditórios. | Quistock governa domínio; AI specs governam serviço; contratos compartilhados referenciam ambos. | specs/001-consolidar-planejamento-ia/research.md Decision 1; Quistock:docs/sdd/README.md; Quistock:docs/sdd/specs/triagem-de-sugestoes.md | Declarações de autoridade delimitadas por projeto/escopo. | Ownership/contratos | Referenciar as duas fontes quando feature de IA alterar regra compartilhada. |
| AUD-018 | Documentação da projeção de evidências do adapter FAQ | implementado | A auditoria encontrou uma afirmação desatualizada em AGENTS.md; ela foi corrigida para registrar que run_faq_node deriva citation_ids e projeta evidências no estado do grafo. | Manter documentação alinhada ao runtime; a migração da tool FAQ para ToolResult continua sendo uma lacuna separada. | AGENTS.md seção 3, wiring do FAQ; src/graphs/adapters.py, run_faq_node | src/graphs/adapters.py retorna evidences/citation_ids; tests/test_graph_adapters.py verifica citation_ids; tests/test_agent_graph.py exercita grafo com evidências; diff de AGENTS.md registra a correção. | Documentação, citações, groundedness. | Manter AGENTS.md alinhado quando adapter/tool mudar; acompanhar separadamente a migração de ToolResult. |

## Itens abertos/divergentes: decisão, impacto e fechamento

| Ref | Dependência / impacto | Próximo owner | Condição de encerramento |
|---|---|---|---|
| AUD-014 | Contrato de dados bloqueia consultas e workflow. | Owners domínio/dados/IA | Contrato versionado, autorizado, com proveniência/exemplos. |
| AUD-015 | Fronteira/identidade bloqueia AUD-009/010 em produção. | Owners APIs/arquitetura dos dois repos | Decisão/ADR e contrato aceitos em ambos. |
| AUD-016 | Sem operação, readiness/SRE não afirmável. | Owners plataforma/IA | Requisitos operacionais verificáveis documentados. |

Confirmado pode ter implementação pendente. Aberto/divergente não cria tarefa runtime e não deve ser resolvido por suposição.

## Rastreabilidade da feature atual

| IDs | Cobertura |
|---|---|
| FR-001..002 | AUD-001..018, diretório Spec Kit e classificação única. |
| FR-003 | current_state/target_state separam decisão e implementação. |
| FR-004..005 | AUD-018 registra a correção do conflito documental; itens ainda abertos estão na tabela de dependências sem tarefa executável. |
| FR-006..010 | AUD-002; fluxo, IDs e trilha requisito-fonte-evidência-ação. |
| FR-011 | Catálogo dos dois repos limitado a fontes pertinentes. |
| FR-012 | AUD-003..008 com evidências de código/testes. |
| FR-013 | A auditoria preservou a discrepância doc/runtime encontrada e a correção em AUD-018; nenhum conflito direto código-teste foi identificado neste recorte. |
| SC-001..003 | Itens do recorte classificados, divergência inicial reconciliada, nenhum aberto vira execução. |
| SC-004 | Nenhuma feature foi explicitamente escolhida, nenhuma spec futura criada. |
| SC-005 | AUD-003..008 mapeiam código/testes. |
| SC-006 | T026 análise final requisito-tarefa. |

## Rubrica/candidatas futuras

Grafo, RAG/citações, guardrails, judge, memória Mongo/Qdrant, job Redis e testes podem contribuir com rubrica (AUD-003..008); isso não prova prontidão operacional nem cobertura acadêmica integral. Spec retrospectiva completa apenas para capacidade necessária à rubrica, conforme research Decision 4.

| Candidata | Status | Prioridade sugerida | Slug provisório | Motivação/dependência |
|---|---|---|---|---|
| Autenticação/identidade API | confirmado, implementação pendente | P1 | autenticacao-identidade-api-ia | AUD-009; depende AUD-015/claims. |
| Contrato read-only/product_workflow | confirmado, implementação pendente | P1 | product-workflow-read-only | AUD-010/AUD-014. |
| Observabilidade/auditoria | confirmado, implementação pendente | P1 | observabilidade-auditoria-ia | AUD-012; SRE/privacidade. |
| MCP/A2A | roadmap confirmado; escopo técnico por definir | P2 | integracoes-mcp-a2a | AUD-011; definir demo/boundary/segurança. |
| Readiness/filas/SLO | aberto | P1 sugerida para readiness | readiness-operacional-ia | AUD-016; decisões operacionais pendentes. |

Prioridades/slugs são sugestões, não aprovação. Nenhuma candidata foi escolhida como próximo ciclo; nenhuma spec futura criada. A equipe escolhe e então roda speckit-specify em specs/.

## Validação e resumo

FEATURE_DIR aponta à feature ativa. spec, plan, research, data-model, contrato, quickstart, checklist e tasks existem. Checklist: 16 marcados. Paths, rótulos e identificadores FR/SC verificados. Testes runtime não executados por ser entrega documental; testes existentes foram inspecionados como evidência da correção registrada em AUD-018. FAQ/memória evidenciados; product_workflow, MCP/A2A e observabilidade não ativos. Lacunas prioritárias: contrato de dados, identidade/fronteira API e operação; resolver decisões antes de selecionar/especificar funcionalidade futura.
