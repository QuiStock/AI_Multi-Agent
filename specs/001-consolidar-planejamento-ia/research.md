# Research: Consolidação do planejamento do serviço de IA

**Feature**: `001-consolidar-planejamento-ia`

**Status**: Concluído para a fase de planejamento documental

## Decision 1: Fonte oficial das decisões ativas

**Decision**: `AI_Multi-Agent/specs` é a fonte oficial das decisões ativas do
serviço de IA. `Quistock/docs/sdd` permanece como contexto histórico e fonte de
referência para decisões interdisciplinares existentes.

**Rationale**: O Spec Kit precisa localizar especificações, planos e tarefas
em uma estrutura previsível. Preservar os documentos anteriores evita perda de
contexto e permite rastrear a origem das decisões.

**Alternatives considered**:

- Migrar tudo e tornar os documentos históricos inválidos: rejeitado porque
  perderia contexto e poderia apagar decisões de outras disciplinas.
- Manter os documentos históricos como fonte principal: rejeitado porque
  decisões novas ficariam fora do fluxo `spec → plan → tasks`.

## Decision 2: Fronteira da auditoria

**Decision**: A primeira auditoria cobre os repositórios `AI_Multi-Agent` e
`Quistock`, incluindo código, testes, documentação, configurações e contratos
que influenciem o serviço de IA e suas integrações.

**Rationale**: O serviço de IA depende de regras de negócio, modelos de dados e
contratos que estão no repositório Quistock; revisar apenas o serviço isolado
ocultaria divergências entre sistemas.

**Alternatives considered**:

- Auditar somente `AI_Multi-Agent`: rejeitado porque não cobre contratos e
  regras externas necessárias à IA.
- Auditar somente documentos selecionados do Quistock: rejeitado para a
  primeira rodada porque a seleção antecipada pode esconder dependências.

## Decision 3: Separação entre decisão e implementação

**Decision**: O status de uma decisão e o status de sua implementação são
  registrados separadamente. Uma decisão pode ser `confirmado` enquanto ainda
  estiver pendente de implementação.

**Rationale**: O planejamento precisa distinguir uma regra aprovada de uma
  lacuna de execução. Isso evita rebaixar uma decisão válida para `proposto`
  apenas porque o código ainda não existe.

**Alternatives considered**:

- Classificar tudo como `divergente` até a implementação: rejeitado porque
  confundiria ausência de implementação com contradição.
- Classificar como `proposto` até o código existir: rejeitado porque o código
  não é condição de validade da decisão.

## Decision 4: Especificações retrospectivas

**Decision**: Capacidades existentes serão registradas na auditoria com suas
  evidências. Uma especificação retrospectiva completa será criada somente
  quando a capacidade for relevante para a rubrica acadêmica. Mudanças e
  funcionalidades futuras sempre terão especificação completa.

**Rationale**: Isso preserva evidências acadêmicas sem transformar cada detalhe
  histórico em uma nova rodada artificial de planejamento.

**Alternatives considered**:

- Criar uma especificação completa para toda capacidade existente: rejeitado
  por gerar documentação duplicada e alto custo de manutenção.
- Não registrar capacidades existentes: rejeitado porque impediria a revisão
  de prontidão e a rastreabilidade acadêmica.

## Decision 5: Conflitos entre código e testes

**Decision**: Quando código e testes divergirem, o item será classificado como
  `divergente`; as duas evidências serão preservadas e uma decisão explícita
  será necessária antes de considerar o comportamento validado.

**Rationale**: Escolher automaticamente código ou teste poderia consolidar um
  bug ou um teste desatualizado como contrato. A divergência precisa ser
  resolvida com evidência e decisão rastreável.

**Alternatives considered**:

- Sempre considerar o código como verdade: rejeitado porque testes podem
  representar um contrato deliberadamente quebrado pelo código.
- Sempre considerar os testes como verdade: rejeitado porque testes podem
  estar desatualizados.

## Decision 6: Forma do resultado

**Decision**: O resultado da feature é composto por artefatos Markdown
  versionados no diretório criado pelo Spec Kit, com checklist, modelo de
  auditoria, contrato documental e guia de validação.

**Rationale**: A equipe precisa revisar e versionar decisões sem introduzir
  banco de dados, endpoint ou alteração de runtime para uma atividade de
  planejamento.

**Alternatives considered**:

- Criar uma ferramenta de inventário executável nesta etapa: rejeitado porque
  aumentaria o escopo antes de estabilizar o modelo de decisão.
- Manter a auditoria somente no chat: rejeitado porque não oferece
  rastreabilidade, revisão por pull request ou reprodutibilidade.
