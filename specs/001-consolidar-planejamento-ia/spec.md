# Feature Specification: Consolidar o planejamento do serviço de IA

**Feature Branch**: `001-consolidar-planejamento-ia`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Revisar e consolidar o planejamento do serviço de IA do Quistock com base no estado atual, nos requisitos acadêmicos e nas decisões existentes."

## Clarifications

### Session 2026-09-30

- Q: Como devemos tratar os documentos de decisão já existentes em
  `Quistock/docs/sdd` durante a consolidação no Spec Kit? → A: Manter os
  documentos antigos como contexto histórico, mas registrar todas as decisões
  vigentes e revisadas nos artefatos do Spec Kit.
- Q: Qual deve ser o alcance da primeira auditoria do serviço de IA? → A:
  Auditar todo o material relevante do repositório, incluindo código, testes,
  documentação, configurações e contratos, excluindo caches, ambientes
  virtuais e segredos.
- Q: Quando uma decisão estiver confirmada na documentação, mas ainda não
  estiver implementada no código, como devemos classificá-la? → A: Manter a
  decisão como `confirmado` e registrar separadamente que sua implementação
  está pendente; usar `divergente` somente quando o comportamento implementado
  contradizer a decisão vigente.
- Q: A auditoria completa deve incluir também o repositório principal
  `Quistock`, além do repositório `AI_Multi-Agent`? → A: Auditar os dois
  repositórios, incluindo suas relações e contratos.
- Q: Quando a auditoria encontrar uma capacidade que já está implementada,
  devemos criar uma especificação retrospectiva completa para ela? → C, com a
  regra adicional de que especificações completas serão priorizadas para
  mudanças ou funcionalidades futuras; capacidades existentes só receberão
  especificação retrospectiva quando forem relevantes para a rubrica acadêmica.
- Q: O que devemos fazer quando a implementação em código e os testes
  divergirem entre si durante a auditoria? → A: Classificar o item como
  `divergente`, preservar as duas evidências e registrar a decisão necessária,
  sem escolher automaticamente uma fonte como correta.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Entender o estado real do serviço de IA (Priority: P1)

Como integrante da equipe do Quistock, quero consultar uma visão consolidada do
que está implementado, planejado e indefinido para entender o ponto de partida
do serviço de IA.

**Why this priority**: Sem separar o estado implementado do estado desejado,
qualquer novo planejamento pode duplicar trabalho ou tratar uma capacidade
planejada como se já existisse.

**Independent Test**: A equipe consegue selecionar qualquer área relevante do
serviço de IA e encontrar sua situação atual, suas evidências e suas lacunas.

**Acceptance Scenarios**:

1. **Given** um artefato relevante do projeto, **When** a equipe o consulta no
   inventário, **Then** encontra sua origem, seu escopo e sua classificação.
2. **Given** uma capacidade descrita na documentação, **When** o código e os
   testes são comparados com essa descrição, **Then** a visão consolidada
   distingue o comportamento implementado do comportamento planejado.

### User Story 2 - Decidir o que deve permanecer no planejamento (Priority: P1)

Como equipe do projeto, quero revisar decisões e divergências em um fluxo
controlado para aprovar, alterar ou manter itens antes de gerar planos de
implementação.

**Why this priority**: Decisões conflitantes sobre autenticação, workflow,
memória, observabilidade e integrações podem causar retrabalho arquitetural.

**Independent Test**: Para cada item classificado como aberto ou divergente,
a equipe consegue registrar uma decisão ou mantê-lo explicitamente pendente,
sem que uma escolha seja inferida silenciosamente.

**Acceptance Scenarios**:

1. **Given** duas fontes com comportamentos diferentes, **When** a equipe faz a
   revisão, **Then** o item é classificado como `divergente` e as duas fontes
   permanecem identificadas.
2. **Given** uma decisão ainda não respondida, **When** a equipe prepara o
   próximo ciclo de planejamento, **Then** o item permanece `aberto` e não
   gera uma tarefa de implementação que dependa dessa decisão.
3. **Given** uma decisão aprovada, **When** ela é incorporada ao planejamento,
   **Then** a especificação correspondente registra a decisão e seus impactos.

### User Story 3 - Planejar uma funcionalidade com rastreabilidade (Priority: P2)

Como integrante da equipe, quero que cada funcionalidade tenha sua própria
especificação, plano, tarefas, critérios de aceite, testes e evidências para
implementar em fatias verificáveis.

**Why this priority**: O serviço é composto por capacidades diferentes, como
FAQ/RAG, memória, Product Workflow, autenticação, MCP, A2A e observabilidade.
Uma especificação única para todo o sistema dificultaria a execução e a
validação acadêmica.

**Independent Test**: Uma funcionalidade aprovada possui os artefatos do fluxo
Spec Kit e cada requisito pode ser ligado a uma tarefa e a uma evidência.

**Acceptance Scenarios**:

1. **Given** uma funcionalidade aprovada, **When** o ciclo de planejamento é
   executado, **Then** são produzidos `spec.md`, `plan.md` e `tasks.md` no
   diretório da própria funcionalidade.
2. **Given** uma tarefa concluída, **When** a equipe revisa a entrega, **Then**
   consegue localizar o requisito, o teste e a evidência correspondentes.
3. **Given** requisitos abertos que mudariam substancialmente a solução,
   **When** as tarefas são geradas, **Then** esses requisitos não produzem
   tarefas executáveis até serem decididos.

### Edge Cases

- O código pode estar mais avançado ou mais atrasado que a documentação; os
  dois estados devem ser registrados separadamente.
- Código e testes podem divergir entre si; nesse caso, ambas as evidências
  devem ser preservadas até que o comportamento correto seja decidido.
- Uma decisão pode estar confirmada nas regras de negócio, mas ainda não estar
  implementada no serviço de IA.
- Um documento antigo pode conter uma proposta que contradiz uma decisão mais
  recente; a contradição deve ser registrada como `divergente` até ser
  resolvida.
- Arquivos gerados, caches, ambientes virtuais e segredos não devem ser
  tratados como especificações ou evidências do produto.
- Uma funcionalidade pode depender de outra ainda aberta; o plano deve tornar
  essa dependência explícita e impedir uma ordem de implementação inválida.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O planejamento MUST manter as especificações de funcionalidades
  do serviço de IA em diretórios criados pelo Spec Kit sob `specs/`.
- **FR-002**: Cada item relevante do planejamento MUST ser classificado como
  `confirmado`, `implementado`, `proposto`, `aberto` ou `divergente`.
- **FR-003**: A revisão MUST distinguir estado atual implementado, arquitetura
  ou comportamento-alvo, roadmap futuro e status da implementação de cada
  decisão; uma decisão pode estar `confirmado` enquanto sua execução permanece
  pendente.
- **FR-004**: Toda divergência MUST identificar as fontes conflitantes, o
  impacto e a decisão necessária; nenhuma divergência pode ser resolvida por
  inferência silenciosa.
- **FR-005**: Requisitos classificados como `aberto` MUST permanecer sem
  tarefas executáveis quando a decisão pendente puder mudar substancialmente a
  solução.
- **FR-006**: Cada funcionalidade aprovada MUST seguir a sequência
  `spec.md`, esclarecimentos, `plan.md`, `tasks.md`, análise de consistência,
  implementação, testes e evidências.
- **FR-007**: Cada requisito desta especificação MUST possuir um identificador
  estável e critérios de aceite observáveis; requisitos não funcionais de
  funcionalidades futuras serão identificados nas respectivas especificações.
- **FR-008**: O planejamento MUST preservar a rastreabilidade entre requisito,
  decisão, contrato, tarefa, código, teste e evidência quando esses elementos
  existirem.
- **FR-009**: O planejamento MUST reutilizar `Quistock/docs/sdd` como contexto
  histórico quando necessário, mas `AI_Multi-Agent/specs` MUST ser a fonte
  oficial das decisões ativas; decisões novas ou revisadas não podem existir
  somente fora dos artefatos do Spec Kit.
- **FR-010**: O ciclo de revisão MUST permitir validar a consistência entre
  `spec.md`, `plan.md` e `tasks.md` antes da implementação.
- **FR-011**: A primeira auditoria MUST abranger os repositórios `AI_Multi-Agent`
  e `Quistock`, incluindo código, testes, documentação, configurações e
  contratos relevantes e suas relações, excluindo caches, ambientes virtuais e
  segredos.
- **FR-012**: Capacidades já implementadas MUST ser registradas na auditoria
  com suas evidências; especificações retrospectivas completas serão criadas
  somente quando forem relevantes para a rubrica acadêmica, enquanto mudanças
  e funcionalidades futuras receberão especificações completas.
- **FR-013**: Quando código e testes divergirem, a auditoria MUST classificar o
  item como `divergente`, preservar as duas evidências e registrar a decisão
  necessária antes de declarar o comportamento como validado.

### Key Entities *(include if feature involves data)*

- **Item de planejamento**: decisão, requisito, regra, capacidade ou restrição
  que precisa ser rastreada; possui descrição, fonte, classificação e impacto.
- **Funcionalidade**: unidade independente de planejamento sob `specs/`, com
  especificação, plano, tarefas e artefatos de validação.
- **Decisão**: escolha aprovada ou pendente que altera escopo, arquitetura,
  contratos, segurança, dados ou execução.
- **Evidência**: código, teste, documento, execução ou demonstração que sustenta
  a classificação de um item.
- **Critério de aceite**: comportamento observável usado para verificar um
  requisito ou uma história de usuário.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% das decisões e requisitos incluídos na primeira auditoria
  possuem uma das cinco classificações acordadas.
- **SC-002**: 100% dos itens classificados como `divergente` identificam as
  fontes conflitantes e a decisão necessária.
- **SC-003**: Nenhum requisito classificado como `aberto` gera tarefa executável
  quando sua decisão puder alterar substancialmente a solução.
- **SC-004**: Cada funcionalidade aprovada possui `spec.md`, `plan.md` e
  `tasks.md` no seu diretório `specs/` antes do início da implementação.
- **SC-005**: A equipe consegue rastrear cada requisito implementado até pelo
  menos um teste ou outra evidência verificável.
- **SC-006**: A análise de consistência identifica requisitos sem tarefas,
  tarefas sem requisito, ambiguidades, duplicações e conflitos antes da
  implementação.

## Assumptions

- O repositório `AI_Multi-Agent` é o local oficial das especificações de
  funcionalidades do serviço de IA.
- `Quistock/docs/sdd` continua disponível como contexto histórico; decisões
  vigentes e revisadas serão registradas nos artefatos do Spec Kit, mantendo a
  relação com o contexto anterior quando isso for relevante.
- O código e os testes existentes representam evidência do estado atual, mas
  não substituem uma decisão de arquitetura-alvo ainda não aprovada.
- A constituição do Spec Kit será preenchida antes de validar o primeiro plano
  de implementação.
- A auditoria considera relevantes, nos dois repositórios, os artefatos que
  influenciam comportamento, contratos, segurança, dados, operação ou
  evidências acadêmicas.
- A revisão inicial não altera código de aplicação, contratos executáveis ou
  comportamento em produção.
