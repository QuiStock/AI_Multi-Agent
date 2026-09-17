# AGENTS.md

Guia operacional e arquitetural para agentes que trabalham neste repositório.
Este arquivo descreve os contratos executáveis, os limites de responsabilidade
e as convenções que devem ser preservadas nas alterações de código.

## Fontes de verdade

Em caso de divergência, use esta ordem:

1. Schemas e tipos existentes em `src/`.
2. Testes automatizados em `tests/`.
3. Decisões e specs aprovadas em `docs/sdd/` quando disponíveis no workspace.
4. Este `AGENTS.md`.
5. README e comentários legados.

Não crie um contrato paralelo para contornar um schema existente. Atualize o
contrato canônico e seus consumidores de forma coordenada.

## Escopo funcional do Quistock

- O sistema é consultivo: agentes consultam, explicam e organizam informações.
- Agentes não recalculam as classes de fluxo produzidas pelo ML.
- O Product Workflow do MVP deve ser somente leitura.
- O Quistock não envia pedidos e não cria, ativa ou encerra promoções.
- Recomendações não podem ser apresentadas como operações já executadas.
- O FAQ responde em português, somente com base em evidências recuperadas, cita
  suas fontes e recusa quando não houver evidência suficiente.
- Não persista raciocínio interno, prompts privados, tokens, credenciais ou
  outros segredos no estado, em resultados de tools ou em logs.

## Stack e runtime

- Python 3.14, gerenciado por `uv`.
- Pydantic para contratos validados em runtime.
- LangChain para agentes, tools e modelos.
- LangGraph para composição do fluxo e estado compartilhado.
- Gemini como modelo principal, com fallback Groq.
- Groq Fast para tarefas rápidas e estruturadas quando configurado.
- Google Generative AI Embeddings para embeddings.
- Qdrant como vector store do FAQ/RAG.
- Documentos `.txt`, `.md` e `.pdf` em `src/data/docs/`.

As configurações pertencem a `src/config.py`. Credenciais vêm do ambiente ou
de `.env`, nunca do código. `src/llm_factory.py` centraliza modelos, embeddings
e structured output; não instancie providers diretamente em agentes novos sem
uma justificativa arquitetural.

## Arquitetura dos agentes

Cada agente deve ser organizado por responsabilidade:

- `card.py`: descrição declarativa e estável da capacidade.
- `<agent>_prompt.py`: instrução de sistema do agente.
- `executor.py`: execução interna, independente da topologia do LangGraph.
- `tools/`: tools estreitas, tipadas e específicas da capacidade.

Nós e adaptadores do LangGraph pertencem a `src/graphs/`, não às pastas dos
agentes. Não crie novos `<agent>_node.py`; executores e adaptadores explícitos
são as fronteiras canônicas de execução.

### Fronteiras de responsabilidade

- O agente conhece seu prompt, card, tools e modelo.
- O executor expõe a operação do agente sem decidir arestas do grafo.
- `src/graphs/adapters.py` traduz `GraphState` para a entrada do executor e
  converte sua saída em uma atualização válida de estado.
- `src/graphs/agent_graph.py` registra nós, arestas, rotas e terminais.
- `src/graphs/decisions.py` concentra decisões condicionais e deve falhar de
  forma controlada quando o estado estiver ausente ou inválido.

## AgentCard

O contrato canônico está em `src/agents/schemas/agent_card.py`.

### Papéis permitidos

- `router`
- `faq_rag`
- `product_workflow`
- `evidence_judge`
- `response_compiler`

### Campos obrigatórios

- `id`: identificador `snake_case`, único no registro.
- `name` e `description`: identificação humana da capacidade.
- `role`: um dos papéis fechados acima.
- `version`: SemVer no formato `x.y.z`.
- `system_prompt_template`: prompt de sistema não vazio.
- `tools`: lista de `ToolBinding`, sem IDs duplicados.
- `memory_policy` e `evidence_policy`: políticas declarativas do agente.

Campos opcionais incluem `failure_policy`, `prompt_variables`, `tags` e
`routing_intents`. Os modelos são imutáveis e rejeitam campos desconhecidos.

### Políticas declarativas

- `MemoryPolicy`: habilitação, modo (`none`, `recent`, `long_term`, `both`),
  limite e TTL.
- `EvidencePolicy`: exigência de evidência, citação e quantidade mínima de
  fontes.
- `FailurePolicy`: comportamento de timeout, tentativas e fallback seguro.
- `PromptVariable`: nome, descrição, obrigatoriedade e origem (`message`,
  `state`, `identity`, `runtime`).

O card descreve a intenção arquitetural, mas não aplica sozinho essas regras.
Ao ativar uma política, implemente também a validação runtime e os testes que
provam seu cumprimento.

### Registro e construção

- Cards disponíveis ficam em `src/agents/registry.py`.
- Atualmente estão registrados `router`, `faq_rag`, `compiler` e
  `evidence_judge`.
- Product Workflow existe nos contratos, mas ainda não possui card registrado
  nesta branch.
- `src/agents/factory.py` resolve tools pelo `ToolRegistry` e cria o agente a
  partir do card.
- O `TOOL_REGISTRY` nasce vazio no código-fonte; a composição da aplicação ou
  os testes precisam registrar implementações antes de criar um agente que
  declare tools.
- Um ID não registrado deve falhar explicitamente; não use fallback silencioso.

## ToolBinding

O contrato declarativo de uma tool fica em
`src/agents/schemas/tool_binding.py`.

- `id`: identificador `snake_case` usado no `ToolRegistry`.
- `name` e `description`: interface apresentada ao agente.
- `properties`: argumentos tipados como `string`, `integer`, `number`,
  `boolean`, `array` ou `object`.
- Cada propriedade declara `required`, podendo ainda restringir `enum` e
  `items_type`.
- `skip_compilation` é metadata declarativa. Não presuma que ela altera o fluxo
  até existir aplicação explícita no runtime e cobertura de testes.

Tools devem ser estreitas e operar sobre consultas ou repositórios definidos.
Não aceite SQL livre produzido pelo modelo. A autorização, o escopo de loja, os
limites, timeouts e filtros devem ser aplicados pelo servidor, não delegados ao
prompt.

## Contrato canônico de retorno das tools

O contrato está em `src/agents/schemas/tool_result.py` e sua versão atual é
`1.0`. Tools novas ou migradas devem retornar `ToolResult[DataT]`.

### Envelope

```text
ToolResult[DataT]
├── schema_version
├── status
├── response
├── data
├── actions
├── evidence
├── warnings
├── error
└── meta
```

Os modelos do contrato são imutáveis e rejeitam campos extras.

### Status

- `success`: operação concluída; não pode conter `error` nem resposta `none`.
- `partial`: exige dados parciais, uma resposta e ao menos `warning` ou `error`
  explicando a incompletude.
- `error`: exige `ToolError`, não pode conter `data`, `actions` ou resposta
  `compose`.

### Modos de resposta

- `direct`: a tool fornece texto final em `ResponseContent`; use apenas quando
  a redação precisa ser fixa e segura.
- `compose`: a tool fornece `intent`, `must_include` e `constraints`; o agente
  redige a resposta usando os dados estruturados.
- `none`: reservado para erros sem mensagem segura para o usuário.

`intent` identifica a finalidade da resposta em `snake_case`; nunca contém o
texto final. `constraints` contém restrições de composição, não fatos de
negócio.

### `must_include`

- Usa JSON Pointer, como `/results/0/content`.
- O caminho é relativo ao conteúdo de `data`, portanto não começa com `/data`.
- Todo pointer precisa existir; o contrato rejeita referências ausentes.
- Itens duplicados não são permitidos.
- Para escapar `/`, use `~1`; para escapar `~`, use `~0`.

### Dados específicos

`data` é o único trecho especializado por tool. Cada agente mantém seus schemas
junto às próprias tools. Não coloque campos de um domínio específico no
envelope genérico.

Exemplos esperados:

```text
ToolResult[FAQSearchData]
ToolResult[ProductDetailsData]
ToolResult[StockMetricsData]
```

### Ações, evidências e avisos

- A ação disponível atualmente é `NavigateAction`, com `target`, `label` e
  parâmetros JSON escalares.
- `ToolEvidence` identifica fonte, conteúdo e metadata para rastreabilidade e
  posterior julgamento.
- `ToolWarning` usa código em maiúsculas e mensagem segura.
- Códigos de erro e warning devem ser estáveis e apropriados para métricas.
- O envelope aceita no máximo 16 ações, 64 evidências e 32 warnings.
- Texto direto tem entre 1 e 6000 caracteres; conteúdo de evidência tem entre
  1 e 12000 caracteres; cada constraint tem entre 1 e 500 caracteres.

### Erros

`ToolError.category` aceita somente:

- `validation`
- `authorization`
- `not_found`
- `dependency`
- `timeout`
- `internal`

`message` deve ser segura. `details` serve para diagnóstico controlado e não é
exposto ao agente. `retryable` informa se a operação pode ser repetida; ele não
autoriza retentativas ilimitadas.

### Metadata

`ToolMetadata` exige:

- `tool_name` em `snake_case`.
- `tool_version` em SemVer.
- `tool_call_id`.
- `trace_id`.
- `timestamp` com timezone.

Propague IDs existentes da requisição. Não gere um novo `trace_id` em cada
camada quando já houver um trace ativo.

### Construção e projeção

- Use `src/agents/tooling/result_factory.py`; não monte envelopes manualmente.
- `ToolResultExtras` agrupa ações, evidências e warnings.
- Use `compose_success`, `direct_success`, `partial_result` e `tool_error`
  conforme o status.
- Use `src/agents/tooling/result_adapter.py` para serialização.
- A visão do agente omite `meta` e `error.details`.
- A visão de estado preserva o contrato completo para auditoria e
  observabilidade.

## Contrato da tool de FAQ

Os schemas canônicos estão em `src/agents/faq/tools/schemas.py`.

- `FAQSearchItem` representa um único trecho recuperado: `file_name`,
  `content`, `relevance` entre 0 e 1 e `page` opcional iniciando em 1.
- `FAQSearchData` representa a consulta completa: `query`, `result_count` e
  `results` com até 20 itens.
- `result_count` deve ser igual a `len(results)`.

O retriever atual ainda produz o formato legado:

```text
arquivo -> file_name
conteudo -> content
relevancia -> relevance
pagina -> page
```

A migração de `faq_search` deve fazer essa conversão antes de construir
`ToolResult[FAQSearchData]`. Nesta branch, `faq_tool.py` ainda retorna `str` e
JSON legado; não documente esse comportamento como contrato final.

## FAQ/RAG

### Regras

- Consulte a base para perguntas sobre políticas, processos ou conhecimento
  documentado.
- Responda somente com material recuperado.
- Cite nome do arquivo e página quando disponível.
- Se não houver evidência, responda de forma controlada sem usar conhecimento
  externo.

### Ingestão

- Extensões aceitas: `.txt`, `.md` e `.pdf`, inclusive em subpastas.
- O pipeline executa leitura, normalização, chunking, embeddings e persistência
  no Qdrant.
- O manifest registra `doc_id`, hash de origem, versão do pipeline, quantidade
  de chunks, status, horário e erro.
- Estados de documento: `indexed` e `failed`.
- Documentos inalterados são ignorados; alterados são substituídos; removidos
  são apagados do Qdrant e do manifest.
- Falha em um documento deve ser registrada sem marcar o documento como
  indexado e sem inventar resultados.

### Recuperação

- `QdrantRetriever` usa `top_k=4` e `min_score=0.3` por padrão.
- Resultados abaixo do score mínimo são descartados.
- A busca registra contagem de candidatos, resultados, ausência de resultados
  e duração.
- Mudanças de relevância precisam atualizar casos em
  `tests/test_rag_evaluation.py`.

## Estado compartilhado do LangGraph

`src/graphs/state.py` é o único contrato canônico do estado. Não crie outro
`GraphState` e não adicione chaves ad hoc em nós ou executores.

### Grupos de dados

- `request`: `request_id`, `user_id`, `conversation_id` e mensagem sanitizada.
- `messages`: mensagens LangChain com reducer `add_messages`.
- `memory`: mensagens recentes e resumos anteriores; atualmente opcional.
- `input_guardrail` e `output_guardrail`: decisões de segurança.
- `routing_decision`: rota, alvo, outcome e motivo.
- `agent_results`: resultados normalizados por agente.
- `evidences`: evidências compartilhadas.
- `response_draft`: rascunho antes da validação de saída.
- `final_response`: resposta liberada ou controlada.
- `status`: ciclo do turno.
- `errors`: erros operacionais normalizados.

### Subcontratos fechados

- `RequestContext`: `request_id`, `user_id`, `conversation_id` e
  `sanitized_message` opcional.
- `ChatMessage`: role `user` ou `assistant`, conteúdo e `created_at`.
- `ConversationSummary`: `conversation_id`, resumo e `created_at`.
- `MemoryContext`: mensagens recentes e resumos de conversas anteriores.
- `InputGuardrailResult`: status `passed` ou `blocked`, código, motivo,
  redações e mensagem sanitizada opcional.
- `OutputGuardrailResult`: status `passed` ou `blocked`, código, motivo e
  violações.
- `RoutingDecision`: rota, agente alvo opcional, motivo e outcome
  `dispatch`, `clarification_required` ou `out_of_scope`.
- `Evidence`: ID, conteúdo, metadata textual e tipo `metric` ou
  `faq_document`.
- `ResponseDraft`: conteúdo, citações e status `draft` ou `blocked`.
- `FinalResponse`: conteúdo e status `success`, `rejected`,
  `clarification_required`, `out_of_scope` ou `error`.
- `AgentError`: agente, código, mensagem segura e indicador `retryable`.

### Rotas e status

Rotas permitidas:

- `faq`
- `product_workflow`
- `clarification_required`
- `out_of_scope`

Status do turno:

- `pending`
- `in_progress`
- `completed`
- `failed`

Rotas podem existir no tipo antes de sua capacidade estar ativa. O roteador só
pode despachar para as rotas presentes em `capabilities`; as demais devem cair
em resposta controlada.

### Resultados dos agentes

- FAQ: status, `answer`, `citation_ids` e erro opcional.
- Product Workflow: status, `answer`, `evidence_ids` e erro opcional.
- Judge: status (`approved`, `insufficient_evidence`, `invalid`), motivo e IDs
  das evidências avaliadas.

`agent_results` usa reducer por nome do agente. Uma atualização de FAQ não pode
apagar o resultado do judge ou de outro agente.

`evidences` usa reducer por `evidence_id`. Um ID repetido substitui a versão
anterior; IDs diferentes são preservados.

### Ownership de escrita

- Input guardrail: `input_guardrail`, mensagem sanitizada e status inicial.
- Context enrichment: `memory`; no MVP é no-op.
- Router: `routing_decision`.
- Capacidade especializada: sua chave em `agent_results` e suas evidências.
- Judge: `agent_results.judge`.
- Compiler: `response_draft`.
- Output guardrail/finalização: `output_guardrail`, `final_response` e status
  terminal.

`agent_outputs` e `validation` não pertencem ao `GraphState`. Executores e
adaptadores devem usar apenas `agent_results`, `evidences`, `response_draft` e
os demais campos canônicos definidos em `src/graphs/state.py`.

## Contratos de fronteira do grafo

`src/graphs/contracts.py` contém modelos validados em runtime:

- `RouteDecision`: rota fechada e motivo entre 1 e 240 caracteres.
- `CompilerResult`: conteúdo entre 1 e 4000 caracteres e status final fechado.

Saída estruturada inválida deve falhar de forma controlada; nunca use conteúdo
parcial do modelo como se tivesse sido validado.

O fluxo canônico é:

```text
START
  -> input_guardrail
  -> context_enrichment
  -> router
  -> capability
  -> compiler
  -> judge
  -> output_guardrail
  -> finalize_output
  -> END
```

Entradas bloqueadas, pedidos de esclarecimento, solicitações fora de escopo e
reprovação do judge terminam em respostas controladas.

## Guardrails

Guardrails são controles adicionais e não agentes.

- Entrada: rejeita vazio e excesso de tamanho, mascara dados sensíveis, detecta
  injection e solicitações internas e pode usar classificação semântica.
- Saída: valida tamanho e Markdown, remove emojis quando configurado, exige
  fontes do FAQ e bloqueia alegações comerciais fora do escopo.
- Resposta compilada pode ser avaliada contra materiais fornecidos.
- Indisponibilidade do classificador ou avaliador deve respeitar `fail_closed`.
- O judge avalia o `response_draft` produzido pelo compilador contra o conteúdo
  completo das evidências. Sua aprovação evita repetir a mesma validação
  semântica no output guardrail, mas não elimina validações determinísticas.

Resultados de guardrail usam `status`, `reason_code`, `reason` e coleções de
redações ou violações. Mensagens bloqueadas devem usar resposta controlada e
não revelar regras internas.

## Memória e observabilidade

- `src/memory/service.py` é apenas a fronteira reservada para enriquecimento de
  contexto; memória durável ainda não está implementada nesta branch.
- O snapshot de memória deve ser somente leitura durante o turno.
- `src/observability/audit.py`, `metrics.py` e `traces.py` ainda são
  placeholders.
- Mesmo antes da implementação final, preserve `request_id`, `tool_call_id` e
  `trace_id` nas fronteiras que já os suportam.
- Não registre conteúdo sensível, credenciais ou prompts privados em logs.

## Testes obrigatórios

Mudanças devem incluir testes proporcionais ao risco:

- Cards: validação, duplicidade, versão e campos desconhecidos.
- Tools: contrato, erros, partial, JSON Pointer, serialização e schema de data.
- Roteamento: dispatch, clarification, out of scope e fallback inválido.
- Estado: reducers, ownership e campos opcionais.
- FAQ/RAG: ingestão, mudança de documentos, relevância, ausência de evidência e
  citações.
- Guardrails: aprovação, bloqueio, sanitização, falha fechada e groundedness.
- Fluxo: input bloqueado, judge bloqueado, compilação e finalização.
- Tools comerciais futuras: autorização, SQL arbitrário, injection e acesso
  entre lojas.

Não reduza cobertura nem adicione exclusões sem justificativa.

## Pipeline e comandos

A CI roda em pull requests para `main` e pushes em `main`, usando Python 3.14 e
dependências travadas pelo `uv.lock`.

Execute antes de enviar uma alteração:

```text
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ruff check src --select C90,PLR,SIM,PERF
uv run mypy .
uv run pytest
uv run pytest -m integration
```

A cobertura unitária e de integração é combinada pela CI e deve permanecer em
pelo menos 80%.

## Checklist de alteração

Antes de concluir:

1. Confirme o contrato canônico afetado.
2. Preserve a separação entre agente, executor, adapter e grafo.
3. Não introduza campos fora de `GraphState`.
4. Não monte `ToolResult` manualmente quando houver factory apropriada.
5. Não exponha `meta`, `error.details`, credenciais ou raciocínio interno ao
   modelo.
6. Garanta fallback controlado para dependências e structured output inválido.
7. Atualize testes de contrato e integração.
8. Rode lint, formatação, code smells, MyPy, testes e cobertura.
9. Atualize este arquivo quando um contrato ou fronteira arquitetural mudar.
