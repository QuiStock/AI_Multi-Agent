# Feature Specification: Product Workflow read-only

**Feature Branch**: `005-product-workflow-read-only`

**Created**: 2026-10-02

**Status**: Implemented (PostgreSQL read-only direto; integração depende de Docker)

**Input**: implementar o Product Workflow como capacidade consultiva do
serviço de IA, sem executar operações comerciais.

## Objetivo

Disponibilizar ao chatbot consultas explicativas sobre sugestões publicadas pelo
ML e a triagem do fluxo do Quistock, mantendo autorização por identidade,
cargo e loja e fornecendo evidências estruturadas para o juiz.

O agente não recalcula classificações, não cria ou altera sugestões e não
executa pedidos ou promoções.

## Clarificações registradas — 2026-10-02

- A primeira entrega atende funcionários e gerentes. O gerente regional fica
  fora desta etapa porque a autenticação atual não o aceita.
- O primeiro recorte cobre busca, card da sugestão e triagem. Os campos da
  sugestão ficam em `suggestion`; `suggestion_decision` nunca é consultada e
  `suggestion_log` só é consultada para excluir sugestões expiradas.
- A tabela `suggestion` do arquivo `quistock-updated.sql` é a referência dos
  campos comerciais da sugestão. Nenhum campo adicional será inventado no
  contrato.
- `MONITO` fica fora das duas tools de sugestões, que retornam somente ações
  `ORDER` e `PROMOTION`.
- Para cada produto e loja, a consulta deve mostrar somente a sugestão ativa
  mais recente. Sugestões rejeitadas, substituídas ou sem disponibilidade para
  triagem não devem aparecer como sugestão ativa.
- A evidência externa deve conter, no mínimo, `evidence_id` e `source_id`. O
  servidor resolve a fonte original; o modelo não escolhe uma fonte nem cria
  identificadores para parecer fundamentado.
- Read-only significa consultar e explicar: a capacidade pode executar
  somente leituras autorizadas e não pode inserir, atualizar ou excluir
  registros, aprovar/recusar sugestões, enviar pedidos ou ativar promoções.
- Nesta etapa, Redis permanece local no Docker Compose. MongoDB e Qdrant são
  resolvidos pelas URLs do `.env` de cada ambiente, sem URLs fixas na spec.
- A FastAPI de IA consulta diretamente o PostgreSQL comercial com a credencial
  configurada para leitura. Não haverá provider HTTP/Spring intermediário para
  o primeiro recorte.

### Decisão fechada nesta rodada

As duas tools ativas não consultam `suggestion_decision` e não retornam
`suggestion_log`. O gerente recebe, além do card, somente os dados de
`suggestion_triage`; portanto a capacidade não afirma aprovação, rejeição,
justificativa ou decisor.

## Estado atual

### Decisões confirmadas

- O Product Workflow é consultivo e read-only no MVP.
- O ML é a fonte da classificação `ALTO`, `NORMAL` ou `BAIXO`; o LLM apenas
  consulta e explica dados publicados.
- O fluxo de domínio distingue métricas, análises, sugestões, triagem e
  decisões gerenciais. A aprovação do Quistock não significa que pedido ou
  promoção foram executados fora do aplicativo.
- O acesso deve ser isolado por usuário, papel, loja e, quando aplicável,
  região. A autorização pertence ao servidor/repositório, não ao prompt.
- A resposta deve separar texto, dados estruturados, evidências, status,
  warnings, erros e correlação.

### Estado implementado

- `product_workflow` existe em `RouteName`, `ProductWorkFlowResult` e nos
  papéis aceitos de `AgentCard`.
- Há card, executor, tools read-only, repositório PostgreSQL e seleção da
  sugestão ativa mais recente em `src/agents/product_workflow/`.
- `src/api/dependencies.py` registra `product_workflow` no grafo HTTP usando o
  mesmo pool PostgreSQL criado pela API para autenticação.
- O arquivo `quistock-schema.sql` confirma a estrutura persistida de
  `suggestion`, `suggestion_triage` e `suggestion_log`. As queries diretas usam
  essas tabelas, `user_account` e `user_store` para aplicar o escopo autorizado.

## Escopo funcional

### Consultas permitidas

O agente expõe exatamente duas tools, conforme a intenção roteada e o escopo
autorizado:

- `get_suggestion_for_product(product_query)`: busca por nome, SKU ou
  categoria e retorna candidatos numerados;
- `get_suggestion_detail(selection_ref)`: revalida a seleção e retorna o card;
  para gerente, acrescenta somente a triagem do funcionário.

### Operações proibidas

- criar, editar, excluir, encaminhar, aprovar ou recusar sugestão;
- recalcular fluxo, validade próxima, quantidade ou desconto;
- criar, enviar ou acompanhar pedido;
- criar, ativar, finalizar ou cancelar promoção;
- consultar loja, região, produto ou sugestão fora do escopo derivado pelo
  servidor;
- executar SQL construído pelo modelo ou aceitar identificadores de escopo do
  texto como autorização.

## Decisões e dependências

| ID | Decisão | Estado | Proposta inicial | Impacto |
|---|---|---|---|---|
| PW-DEC-001 | Serviço proprietário dos dados | confirmado nesta rodada | FastAPI possui acesso direto somente leitura ao PostgreSQL comercial para o Product Workflow; Spring continua proprietária das escritas e dos CRUDs | Exige credencial sem escrita, queries parametrizadas, timeout, índices, auditoria e ADR de ownership |
| PW-DEC-002 | Modelo canônico | confirmado | Usar os campos persistidos em `suggestion` e consultar `suggestion_triage` somente para a visão do gerente | Exige DTOs versionados e testes de consistência da projeção |
| PW-DEC-003 | Atores | confirmado para a primeira entrega | Funcionário e gerente; gerente regional bloqueado pela autenticação atual | Evita prometer escopo que o ambiente não autoriza |
| PW-DEC-004 | Escopo de loja/região | confirmado | Derivar no servidor a partir da identidade autenticada; nunca aceitar `store_id` do body | Define filtros e testes entre lojas |
| PW-DEC-005 | Intenções do router | confirmado para a primeira entrega | `suggestions` e `suggestion_detail`; métricas/análises e decisões ficam fora do recorte | Define dispatch sem ampliar o primeiro recorte |
| PW-DEC-006 | Freshness e indisponibilidade do ML | confirmado como requisito; política detalhada aberta | Expor data de corte, versão e `last_updated`; mostrar somente a sugestão ativa mais recente e avisar quando a publicação estiver desatualizada | Evita apresentar dado antigo como atual |
| PW-DEC-007 | Evidência do workflow | confirmado no mínimo | Toda afirmação factual deve carregar `evidence_id` e `source_id` resolvidos a partir de uma fonte original | Exige alinhamento do contrato `Evidence` e do judge |
| PW-DEC-008 | Limites operacionais | confirmado | Somente leitura, limite de linhas, timeout por consulta, seleção da sugestão ativa mais recente e auditoria sem PII desnecessária | Define proteção do serviço |

## Arquitetura-alvo proposta

```text
JWT validado
  -> identidade + cargo + escopo derivado no servidor
  -> Router
  -> Product Workflow Agent
  -> tools read-only tipadas
  -> PostgreSQL comercial (credencial read-only; queries parametrizadas)
  -> resultados + evidências
  -> Compiler
  -> Evidence Judge
  -> Output Guardrail
```

O Product Workflow acessa diretamente somente as tabelas necessárias para
leitura. O LLM nunca recebe SQL livre e não possui conexão com o banco. A
FastAPI não executa comandos de escrita; a API Spring continua sendo a
proprietária das mutações comerciais. O ADR
`adr-001-product-workflow-direct-postgres.md` registra credencial, tabelas,
transações, compatibilidade, auditoria e impacto dessa decisão.

Neste documento, “read-only” não significa que o chatbot apenas repete texto.
Ele pode consultar dados atuais, filtrar pelo escopo autorizado e explicar a
origem dos valores. A restrição é que nenhuma dessas consultas pode produzir
efeito comercial ou alterar o estado do sistema.

## Contrato interno proposto

### Contexto autorizado

O executor recebe o contexto estabelecido pela API, nunca valores escolhidos
por prompt:

```json
{
  "request_id": "request-123",
  "trace_id": "trace-123",
  "email": "usuario@exemplo.com",
  "role_id": 2,
  "authorized_at": "2026-10-02T12:00:00Z"
}
```

O email e o cargo são estabelecidos pela API. O repository consulta o vínculo
ativo em `user_store` para relacionar o usuário às lojas permitidas. O cliente
não pode ampliar esse contexto enviando outro email, cargo ou loja.

### Tools read-only propostas

As tools são chamadas de repositório/API predefinidas, com argumentos
tipados. O modelo fornece apenas filtros de consulta; o servidor injeta o
escopo autorizado e aplica limites.

| Tool ID | Finalidade | Entradas possíveis | Saída |
|---|---|---|---|
| `get_suggestion_for_product` | Buscar sugestões por produto | `product_query` | lista numerada de candidatos autorizados |
| `get_suggestion_detail` | Consultar o card selecionado | `selection_ref` | campos de `suggestion`, produto, lote físico e, para gerente, `suggestion_triage` |

Nenhuma tool terá `create`, `update`, `delete`, `approve`, `reject`, `send`,
`execute`, decisão gerencial, histórico de logs ou SQL livre. A referência
recebida pelo modelo será validada novamente contra o escopo no serviço
proprietário.

### Resposta do agente

A resposta deverá usar o envelope interno `ToolResult` já adotado pelo
serviço, com `schema_version`, `status`, `response`, `data`, `evidence`,
`warnings`, `error` e `meta`. O executor deve produzir uma projeção segura para
o compiler, sem expor credenciais, SQL, prompts ou detalhes internos.

Exemplo ilustrativo, ainda não contrato fechado. Os únicos campos de evidência
obrigatórios nesta etapa são `evidence_id` e `source_id`; os demais metadados
dependem do contrato final do juiz:

```json
{
  "schema_version": "1.0",
  "status": "success",
  "response": "O produto foi classificado como ALTO na janela publicada.",
  "data": {
    "product_id": "product-123",
    "store_id": "store-123",
    "flow_class": "ALTO",
    "analysis_cutoff": "2026-09-30",
    "model_version": "ml-2026.09"
  },
  "evidence": [
    {
      "evidence_id": "analysis-product-123-2026-09-30",
      "source_id": "analysis-456",
      "content": "Classificação publicada pelo ML.",
      "metadata": {
        "entity_type": "ml_analysis",
        "store_id": "store-123",
        "source_version": "ml-2026.09",
        "freshness": "2026-09-30T00:00:00Z",
        "request_id": "request-123",
        "trace_id": "trace-123"
      }
    }
  ],
  "warnings": []
}
```

O tipo da fonte e os metadados adicionais precisam ser alinhados ao `Evidence`
atual, que hoje aceita somente `metric` e `faq_document`. Isso não elimina a
exigência de uma fonte original nem autoriza evidência criada pelo LLM.

## Regras de autorização

- Funcionário: somente sugestões `IN_EMPLOYEE_TRIAGE` com
  `available_for_triage = TRUE` da própria loja.
- Gerente: somente sugestões `SENT_TO_MANAGER` da loja administrada, em modo
  read-only.
- Ambos: qualquer sugestão com evento `EXPIRED` em `suggestion_log` é excluída.
- Regional: fora da primeira entrega; a autenticação atual não aceita esse
  papel nas rotas protegidas da IA.
- Qualquer outro papel ou contexto sem escopo válido: resposta controlada,
  sem consulta comercial.
- Um `store_id`, `region_id`, email ou cargo recebido no body, query, prompt ou
  resultado do LLM não amplia autorização.
- Toda consulta comercial deve usar filtros parametrizados, limite de linhas,
  timeout, correlação e auditoria segura.

## Falhas e groundedness

| Situação | Comportamento |
|---|---|
| Identidade ou escopo ausente | Não consultar dados; retornar `authorization` controlado |
| Loja fora do escopo | Não revelar se o recurso existe; retornar `not_found` ou resposta equivalente segura |
| PostgreSQL indisponível | Retornar `dependency`/`unavailable`; não inventar dados |
| Timeout | Retornar `timeout`, marcado como retryable apenas quando seguro |
| Schema inválido | Descartar resultado e registrar erro técnico seguro |
| Nenhuma sugestão autorizada | Informar ausência de evidência; não inventar dados |
| Sugestão sem triagem | Informar os dados disponíveis, sem inferir aprovação |
| Judge sem evidência suficiente | Bloquear resposta factual e usar resposta controlada |

## Critérios de aceite

- **CA-PW-001**: Given uma busca por produto, when existem vários candidatos,
  then a resposta apresenta uma lista numerada e aguarda a escolha.
- **CA-PW-002**: Given um funcionário autenticado, when consulta sugestões,
  then somente sugestões `IN_EMPLOYEE_TRIAGE` com
  `available_for_triage = TRUE` da própria loja são retornadas.
- **CA-PW-003**: Given um gerente autenticado, when consulta sugestões, then
  somente sugestões `SENT_TO_MANAGER` da própria loja são retornadas.
- **CA-PW-004**: Given uma sugestão `SENT_TO_MANAGER`, when o gerente consulta
  o card, then o agente informa apenas a triagem disponível e não afirma
  aprovação, recusa ou decisor.
- **CA-PW-005**: Given um funcionário de `store-A`, when solicita dados de
  `store-B`, then nenhuma linha ou detalhe de `store-B` é retornado.
- **CA-PW-006**: Given entrada contendo SQL, instrução de ignorar escopo ou
  `store_id` arbitrário, when uma tool é chamada, then o servidor ignora a
  tentativa e mantém o escopo autenticado.
- **CA-PW-007**: Given PostgreSQL comercial indisponível, when a consulta é executada,
  then o agente retorna falha controlada sem inventar números ou decisões.
- **CA-PW-008**: Given uma resposta sem fonte original, when chega ao judge,
  then ela é marcada como insuficiente e não é liberada como fato.
- **CA-PW-009**: Given qualquer consulta do Product Workflow, when termina,
  then não há escrita em sugestão, decisão, pedido, promoção ou PostgreSQL
  comercial pelo serviço de IA.
- **CA-PW-010**: Given uma consulta válida, when o serviço registra telemetria,
  then request/trace, agente, tool, status e latência são correlacionáveis sem
  persistir token, prompt privado ou PII desnecessária.

## Testes obrigatórios

- card, registry e executor do `product_workflow`;
- roteamento das intenções e rota inativa/fora de escopo;
- contrato de cada tool e envelope `ToolResult`;
- isolamento por usuário, cargo, loja e região;
- tentativa de SQL livre, prompt injection e troca de `store_id`;
- ausência de mutações usando mocks que falham se houver escrita;
- dados ausentes, seleção inválida, sugestão expirada e sugestão inexistente;
- timeout, indisponibilidade, schema inválido, limite de linhas e retry;
- evidências entregues ao judge e bloqueio sem evidência;
- integração read-only contra PostgreSQL com a massa derivada de
  `quistock-updated.sql`;
- verificação de que a credencial usada pela API falha em `INSERT`, `UPDATE` e
  `DELETE`.

## Dependências e bloqueios

- Provisionar e validar a credencial PostgreSQL somente leitura usada pela
  FastAPI, conforme o ADR de acesso direto.
- Resolver a divergência de autorização do regional manager entre a regra de
  domínio e a feature de autenticação da API de IA.
- Validar os grants efetivos do read model de produto/sugestão no ambiente.

## Fora do escopo

- executar pedido ou promoção;
- alterar sugestão ou decisão;
- recalcular ML;
- criar uma nova tela ou endpoint comercial mutável;
- acesso livre ao PostgreSQL pelo LLM ou SQL construído pelo modelo;
- expor prompts, cadeia de pensamento ou credenciais;
- resolver a divergência de regional manager por suposição.
