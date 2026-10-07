# Feature Specification: Product Workflow consultivo para sugestões de produto

> Superseded by `specs/005-product-workflow-read-only`. The active contract
> exposes exactly `get_suggestion_for_product` and `get_suggestion_detail`,
> uses PostgreSQL as the source of truth, and does not use a client card
> snapshot as a Product Workflow tool input.

**Feature Branch**: `product_workflow`  
**Created**: 2026-10-01  
**Status**: Superseded
**Input**: Criar o agente Product Workflow que orienta funcionários e gerentes sobre o produto de um card de sugestão. A requisição pode trazer um snapshot estruturado do card. Para perguntas sobre outro produto ou sem card, uma tool consulta o PostgreSQL e devolve informações no mesmo contrato de card.

## Clarifications

### Session 2026-10-01

- Q: Se o nome informado corresponder a mais de um produto diferente na loja do usuário, como o agente deve descobrir qual deles ele quer? → A: Mostrar somente as informações necessárias para distinguir as opções e pedir ao usuário que escolha antes de responder.

## User Scenarios & Testing

### User Story 1 - Entender o card aberto (Priority: P1)

Como funcionário ou gerente, quero perguntar ao chatbot sobre o card de produto aberto para entender os dados e a sugestão apresentados nele.

**Why this priority**: O botão de ajuda do card deve contextualizar o chatbot sem obrigar uma nova busca de dados.

**Independent Test**: Enviar uma pergunta sobre o produto do card com seu snapshot estruturado e verificar que a resposta usa somente esse snapshot, sem consultar o banco comercial.

**Acceptance Scenarios**:

1. **Given** uma requisição com snapshot estruturado de card, **When** a pergunta tratar do produto desse card, **Then** o Product Workflow responde usando o snapshot recebido sem validar ou consultar esse produto no banco.
2. **Given** uma pergunta que solicite justificativa não contida no snapshot, **When** não houver evidência para justificá-la, **Then** o agente informa a limitação e não inventa a razão da recomendação.
3. **Given** o snapshot recebido no body, **When** ele for incluído como evidência para o juiz, **Then** sua origem fica identificada como dado fornecido pelo cliente e não como dado verificado no banco.

### User Story 2 - Consultar outro produto ou iniciar sem card (Priority: P1)

Como funcionário ou gerente, quero perguntar sobre outro produto ou iniciar uma conversa sem card para receber as informações de uma sugestão vigente que eu possa acessar.

**Why this priority**: O chatbot também precisa apoiar consultas além do card que abriu a conversa, mantendo a resposta consistente com os cards do aplicativo.

**Independent Test**: Fazer uma pergunta sobre produto diferente do snapshot, ou sem snapshot, e verificar que a tool retorna dados estruturados no contrato de card, limitados ao escopo autorizado e sem sugestões expiradas.

**Acceptance Scenarios**:

1. **Given** uma pergunta sobre produto diferente do produto do snapshot, **When** o agente consultar a tool, **Then** ela busca a sugestão vigente desse produto e retorna os dados no mesmo formato estruturado do card.
2. **Given** uma requisição sem snapshot de card e com produto identificável na pergunta, **When** o agente consultar a tool, **Then** a resposta é baseada no card estruturado retornado pela consulta.
3. **Given** uma sugestão substituída com evento `EXPIRED` em `suggestion_log`, **When** a tool buscar a sugestão vigente, **Then** ela exclui essa sugestão e considera somente registros sem evento de expiração.
4. **Given** funcionário autenticado, **When** a tool consultar sugestões, **Then** retorna somente registros com `available_for_triage = TRUE` dentro da loja autorizada.
5. **Given** gerente autenticado, **When** a tool consultar sugestões, **Then** retorna somente registros com status `SENT_TO_MANAGER` dentro da loja autorizada.
6. **Given** que a API central marque como expirada uma sugestão substituída do mesmo produto e loja, inclusive quando o tipo da nova sugestão for diferente, **When** a tool fizer a busca, **Then** a sugestão substituída não será apresentada como vigente.
7. **Given** que o nome informado corresponda a mais de um produto distinto na loja autorizada, **When** a busca retornar essas correspondências, **Then** o agente apresenta apenas as informações necessárias para distingui-los (como nome, categoria ou SKU, quando necessário) e aguarda a escolha do usuário antes de responder sobre uma sugestão.

### User Story 3 - Receber resposta segura em busca vazia ou indisponível (Priority: P1)

Como usuário, quero saber quando não há sugestão vigente ou quando a consulta está indisponível para não receber informações inventadas ou desatualizadas.

**Why this priority**: Ausência de resultado e falha técnica precisam ser comunicadas corretamente e de forma distinta.

**Independent Test**: Simular nenhum resultado elegível e indisponibilidade do banco, verificando respostas restritivas distintas e ausência de dados expirados.

**Acceptance Scenarios**:

1. **Given** que não exista sugestão vigente correspondente dentro do escopo autorizado, **When** a tool concluir a busca sem resultados, **Then** retorna resultado estruturado de não encontrado e o agente informa que não encontrou sugestão vigente para o produto, sem alegar que o produto não existe.
2. **Given** que a consulta ao banco falhe ou esteja indisponível, **When** a tool não puder concluir a busca, **Then** retorna falha de dependência e o agente informa que não conseguiu consultar os dados naquele momento, sem dizer que não encontrou sugestão.

## Requirements

### Functional Requirements

- **FR-001**: A requisição pode conter um objeto estruturado opcional com o snapshot do card, incluindo os dados exibidos ao usuário, como produto, categoria, quantidade, validade e parâmetro da sugestão.
- **FR-002**: Quando a pergunta se referir ao produto do snapshot recebido, o Product Workflow MUST usar esse snapshot diretamente e MUST NOT consultar ou validar esse produto no banco.
- **FR-003**: Quando a pergunta se referir a outro produto, ou não houver snapshot, o Product Workflow MUST consultar uma tool predefinida que monta e retorna o contrato de card para o produto perguntado; a consulta MUST NOT ser SQL livre gerado pelo modelo.
- **FR-004**: O resultado da consulta SQL MUST usar o mesmo formato estruturado do snapshot de card aceito na requisição e conter apenas informações necessárias para representar o card.
- **FR-005**: A consulta MUST ser somente leitura, parametrizada e restrita aos dados que o usuário autenticado pode acessar.
- **FR-006**: A identidade e o cargo MUST ser estabelecidos pelo processo de autenticação existente a partir do email validado e da consulta de `role_id` no PostgreSQL; `role_id = 2` representa gerente e `role_id = 3` representa funcionário. O cliente MUST NOT escolher sua identidade, cargo ou escopo de loja no payload.
- **FR-007**: A tool MUST aplicar o escopo de loja na própria consulta, derivando a loja autorizada a partir do usuário autenticado e dos vínculos ativos no banco, sem exigir uma etapa adicional de autenticação.
- **FR-008**: Para funcionário, a consulta MUST limitar resultados a sugestões
  com status `IN_EMPLOYEE_TRIAGE` e `available_for_triage = TRUE`; para gerente,
  MUST limitar a sugestões com status `SENT_TO_MANAGER`.
- **FR-009**: Uma sugestão MUST ser excluída do conjunto vigente quando houver registro relacionado em `suggestion_log` com `event = 'EXPIRED'`. A API central garante o registro desse evento quando uma sugestão é substituída; não faz parte desta feature alterar o script SQL.
- **FR-010**: Quando uma nova sugestão do mesmo produto e loja substituir a anterior, a expiração MUST ocorrer independentemente de a nova sugestão ter o mesmo tipo ou outro tipo.
- **FR-011**: Se a busca não encontrar sugestão vigente dentro do escopo, a tool MUST retornar um resultado estruturado de não encontrado e o agente MUST responder de modo restritivo, sem afirmar que o produto não existe ou recorrer a sugestão expirada.
- **FR-012**: Se a consulta falhar ou o banco estiver indisponível, a tool MUST retornar uma falha de dependência distinta de não encontrado; o agente MUST informar indisponibilidade temporária, sem inventar dados.
- **FR-013**: O snapshot enviado pelo cliente pode ser usado diretamente como evidência para o juiz, sem validação adicional no banco. Sua proveniência MUST permanecer distinguível de dados retornados pela tool; o juiz avalia suporte/consistência da resposta, não autenticidade do snapshot.
- **FR-014**: O agente MUST limitar explicações a dados presentes no snapshot ou no contrato retornado pela tool. Se perguntado por justificativa ou métrica ausente dessas evidências, MUST declarar que não dispõe dessa informação e não inferir a razão da recomendação.
- **FR-015**: O Product Workflow MUST permanecer consultivo e MUST NOT criar, editar, encaminhar, aprovar, recusar ou executar sugestões, pedidos ou promoções.

- **FR-016**: Quando o nome informado corresponder a mais de um produto distinto dentro da loja autorizada, o agente MUST apresentar somente as informações necessárias para distinguir as opções (por exemplo, nome, categoria ou SKU, conforme necessário) e MUST aguardar que o usuário escolha uma antes de responder sobre uma sugestão.

### Key Entities

- **Snapshot de card**: objeto estruturado opcional enviado na requisição com os valores exibidos no card; é contexto fornecido pelo cliente e não é validado no banco.
- **Contrato de card**: formato estruturado comum ao snapshot da requisição e ao resultado da tool, com as informações visíveis da sugestão e do produto.
- **Identidade autenticada**: email e cargo obtidos/associados pelo servidor durante autenticação, não pelo payload do cliente.
- **Escopo de loja**: vínculo ativo derivado no servidor entre a identidade autenticada e as lojas que pode consultar.
- **Sugestão vigente**: sugestão visível ao cargo do usuário e sem evento `EXPIRED` relacionado em `suggestion_log`.
- **Evidência do Product Workflow**: snapshot fornecido pela requisição ou contrato retornado pela consulta, com sua origem identificada para avaliação do juiz.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Em todos os testes de pergunta sobre o card recebido, o fluxo usa o snapshot e não executa consulta comercial.
- **SC-002**: Em todos os testes de pergunta sobre outro produto ou sem card, o resultado da tool respeita o contrato estruturado do card, o cargo, o escopo da loja e a exclusão de sugestões expiradas.
- **SC-003**: Em todos os testes de autorização, nenhuma sugestão de loja fora do escopo autenticado é retornada.
- **SC-004**: Em todos os testes de ausência de resultado e falha de banco, as respostas são distintas, restritivas e não contêm fatos sem evidência.
- **SC-005**: Em todos os testes do juiz, a origem do snapshot de cliente permanece identificável e respostas com justificativas não presentes nas evidências não são aprovadas.

## Assumptions

- O botão de ajuda do card abre ou direciona para o chatbot enviando o snapshot do card em campos estruturados.
- A fonte comercial consultada pela tool é o PostgreSQL do Quistock, com credencial de leitura e escopo derivado no servidor.
- `suggestion_log.event = 'EXPIRED'` é a fonte existente para excluir sugestões substituídas; o schema não será modificado nesta feature.
- Funcionários e gerentes podem consultar sugestões apenas da loja vinculada a sua identidade; gerente regional permanece fora das rotas protegidas conforme a spec de autenticação.
- O agente não recalcula classificações do ML nem apresenta uma sugestão aprovada como operação comercial executada.
