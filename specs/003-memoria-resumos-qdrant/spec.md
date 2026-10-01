# Feature Specification: Persistência de turnos e resumos no Qdrant

**Feature Branch**: `003-memoria-resumos-qdrant`
**Created**: 2026-09-30
**Status**: Draft
**Input**: User decision: manter um documento por conversa no MongoDB, acrescentar nele as mensagens dentro do array físico `messages` e retirar completamente o resumo do MongoDB, mantendo-o somente no Qdrant. O exemplo do usuário usa `mensagens` como nome ilustrativo em português; o campo persistido confirmado é `messages`.

## User Scenarios & Testing

### User Story 1 - Continuar uma conversa com histórico durável (Priority: P1)

Como usuário do Quistock, quero que minhas interações continuem registradas no documento da conversa para que ela possa ser retomada sem depender do resumo.


**Why this priority**: As mensagens são a memória conversacional detalhada e devem continuar duráveis mesmo que o resumo passe a ser mantido em outro armazenamento.

**Independent Test**: Registrar várias mensagens e turnos, encerrar e retomar a conversa; verificar que o documento da conversa contém as mensagens em ordem e pertence somente ao usuário autorizado.

**Acceptance Scenarios**:

1. **Given** uma conversa com mensagens registradas, **When** o usuário autorizado a retoma, **Then** as mensagens do array `messages` são recuperadas na ordem original do documento da conversa.
2. **Given** um usuário diferente, **When** tenta ler ou retomar a conversa, **Then** nenhum turno ou resumo dessa conversa é revelado.

### User Story 2 - Usar resumo sem duplicá-lo no MongoDB (Priority: P1)

Como serviço de IA, quero recuperar e atualizar o resumo da conversa sem persistir seu conteúdo no MongoDB para que haja uma única cópia durável do resumo no Qdrant.

**Why this priority**: O usuário confirmou que os resumos devem sair totalmente do MongoDB e permanecer somente no Qdrant.

**Independent Test**: Gerar ou atualizar o resumo de uma conversa e verificar que ele está disponível no Qdrant, não é gravado no MongoDB e pode ser recuperado para o fluxo de memória.

**Acceptance Scenarios**:

1. **Given** turnos novos ainda não resumidos, **When** o resumo é gerado, **Then** seu conteúdo é mantido no Qdrant e não é persistido em documentos MongoDB.
2. **Given** uma falha ao gravar ou atualizar o Qdrant, **When** o resumo não pode ser confirmado, **Then** o sistema não cria uma cópia persistente do resumo no MongoDB.
3. **Given** dados antigos com resumo no MongoDB, **When** a migração é concluída, **Then** resumos válidos permanecem no Qdrant, resumos ausentes são reconstruídos a partir dos turnos e a cópia no MongoDB é removida após verificação.

## Clarifications

### Session 2026-09-30

- Q: Onde o resumo conversacional deve permanecer persistido? → A: Somente no Qdrant; não manter cópia do conteúdo do resumo no MongoDB.
- Q: Como os registros conversacionais serão organizados no MongoDB? → A: Um documento por conversa; as mensagens são acrescentadas ao array físico `messages` (o exemplo original o chamou de `mensagens`), e cada turno é representado pelas mensagens correspondentes do usuário e do assistente. Esta resposta substitui a interpretação anterior de um documento por turno.
- Q: Como tratar resumos legados que já existem no MongoDB? → A: Reaproveitar os resumos válidos já presentes no Qdrant, recriar a partir dos turnos os que estiverem faltando e remover a cópia no MongoDB após verificar a migração.
- Q: Quando o resumo deve ser gerado ou atualizado no Qdrant? → A: Em segundo plano após o encerramento da conversa; o encerramento não aguarda a sumarização.
- Q: O que deve acontecer com os dados quando uma conversa for excluída? → A: Excluir seus turnos do MongoDB e seu resumo do Qdrant.
- Q: Qual comportamento de idempotência, retry e reconciliação deve orientar o resumo assíncrono? → A: Mensagens têm identidade e ordenação estáveis; atualizar o mesmo ponto Qdrant por conversa sem duplicar ou regredir progresso; repetir falhas temporárias com limite e deixar falhas esgotadas observáveis/reprocessáveis; reconciliar conversas encerradas comparando a última mensagem no MongoDB com o progresso registrado no Qdrant; serializar atualizações por conversa e impedir que jobs antigos recriem resumos após exclusão. Parâmetros concretos ficam para o plano.
- Q: Como identificar repetição do evento que agenda o resumo? → A: A aplicação cria uma `closure_key` estável uma vez no evento interno de encerramento e a persiste no job; o ID no Redis referencia esse job. A chave não é fornecida pelo usuário. Repetições do mesmo encerramento reutilizam a mesma chave/job.

## Edge Cases

- A atualização do documento da conversa no MongoDB funciona, mas a atualização do resumo no Qdrant falha ou fica indisponível.
- Um retry de geração ou indexação acontece após timeout e não pode duplicar turnos nem produzir versões inconsistentes do resumo.
- Uma conversa ainda não tem resumo no Qdrant ou o ponto vetorial está desatualizado em relação aos turnos persistidos.
- Uma mensagem chega duplicada ou fora de ordem dentro do array `messages`.
- Uma conversa é retomada enquanto o resumo está sendo atualizado.
- Dados legados ainda contêm resumo no MongoDB durante a transição.
- A recuperação semântica não pode expor resumo de outro usuário nem tratar payload enviado pelo cliente como autorização.

## Requirements

### Functional Requirements

- **FR-001**: O serviço MUST persistir cada conversa em um único documento MongoDB associado ao usuário e acrescentar as mensagens ao array físico `messages`, preservando a ordem; um turno é formado pelas mensagens correspondentes do usuário e do assistente, não por um documento MongoDB separado.
- **FR-002**: O serviço MUST gerar e manter o conteúdo persistido do resumo conversacional somente no Qdrant.
- **FR-003**: O serviço MUST recuperar e atualizar o resumo no Qdrant sem depender de uma cópia do texto do resumo no MongoDB.
- **FR-004**: O MongoDB MUST NOT receber nem manter campos ou documentos cujo conteúdo seja o resumo conversacional; dados legados de resumo deverão ser tratados na transição desta feature.
- **FR-005**: Turnos e resumos MUST permanecer isolados pelo usuário e pela conversa, usando identidade confiável do servidor para leituras e gravações protegidas.
- **FR-006**: Falha de persistência do resumo no Qdrant MUST NOT causar fallback que grave o conteúdo do resumo no MongoDB.
- **FR-007**: O fluxo MUST permitir detectar e reparar divergência entre turnos duráveis no MongoDB e o resumo indexado no Qdrant sem criar uma segunda cópia persistente do resumo no MongoDB.
- **FR-008**: Na transição, o serviço MUST preservar resumos legados válidos no Qdrant, reconstruir a partir dos turnos os resumos ausentes ou inválidos e remover do MongoDB o conteúdo legado somente após a verificação do resultado no Qdrant.
- **FR-009**: Ao encerrar uma conversa, o serviço MUST concluir o encerramento sem aguardar a geração ou atualização do resumo no Qdrant; o processamento ocorre em segundo plano e deve permitir novas tentativas e reconciliação em caso de falha.
- **FR-010**: Quando uma conversa for excluída por solicitação autorizada, o serviço MUST remover seus turnos do MongoDB e o resumo correspondente do Qdrant.
- **FR-011**: Cada mensagem MUST ter identidade estável e ordenação recuperável dentro da conversa para permitir deduplicação de gravações e determinar quais mensagens já foram incorporadas ao resumo.
- **FR-012**: A atualização do resumo MUST ser idempotente por conversa: repetir um job já aplicado não pode criar outro ponto lógico nem reduzir o progresso de mensagens resumidas.
- **FR-013**: Falhas temporárias na atualização do Qdrant MUST gerar retries limitados; falhas que esgotarem as tentativas MUST permanecer observáveis e passíveis de reprocessamento.
- **FR-014**: O serviço MUST reconciliar conversas encerradas comparando a mensagem mais recente persistida no MongoDB com o progresso indicado no Qdrant e agendar correção quando o ponto estiver ausente ou atrasado.
- **FR-015**: Atualizações de resumo da mesma conversa MUST ser serializadas ou protegidas contra gravação fora de ordem; jobs pendentes ou atrasados MUST NOT recriar o ponto de resumo após a exclusão da conversa.

### Key Entities

- **Conversa**: agrupamento lógico de interações de um usuário, identificado por um identificador estável.
- **Turno**: interação do usuário e do assistente representada por mensagens relacionadas dentro do array `messages` do documento da conversa.
- **Mensagem**: elemento de `messages` com identificador estável e posição/ordem estável dentro da conversa.
- **Documento de conversa**: documento MongoDB único por conversa, com metadados e o array ordenado `messages`; não contém o texto do resumo.
- **Resumo conversacional**: representação derivada dos turnos, persistida somente no Qdrant e associada à conversa e ao usuário.
- **Progresso do resumo**: metadado no ponto Qdrant que identifica até qual mensagem/ordem o resumo considera, sem guardar texto de resumo no MongoDB.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Em todos os testes de persistência, uma conversa possui um único documento MongoDB e suas mensagens são recuperadas em ordem após encerramento e retomada.
- **SC-002**: Em todos os testes de gravação e atualização de resumo, seu conteúdo persistido está disponível no Qdrant e ausente dos dados persistidos no MongoDB.
- **SC-003**: Em todos os testes de isolamento, um usuário não consegue recuperar turnos ou resumos associados a outro usuário.
- **SC-004**: Após a transição dos dados legados, nenhuma cópia persistente do conteúdo de resumo permanece no MongoDB e cada resumo migrado possui uma cópia válida no Qdrant ou foi explicitamente marcado como não recuperável.
- **SC-005**: Falhas e retries de atualização permitem convergir o resumo do Qdrant com os turnos de origem sem duplicar turnos nem persistir resumo no MongoDB.
- **SC-006**: O encerramento de uma conversa permanece concluído mesmo quando a atualização do resumo ainda está pendente ou falha temporariamente.
- **SC-007**: Após excluir uma conversa, nenhum de seus turnos permanece no MongoDB e seu resumo não pode mais ser recuperado do Qdrant.
- **SC-008**: Reexecutar uma atualização concluída não duplica nem regride o ponto Qdrant, e atualizações repetidas convergem para a mensagem mais recente da conversa.
- **SC-009**: Uma conversa encerrada cujo resumo esteja ausente ou atrasado em relação ao MongoDB é identificada pela reconciliação e pode ser reprocessada sem duplicar mensagens.
- **SC-010**: Nenhum job atrasado recria o resumo de uma conversa após a exclusão ser concluída.

## Assumptions

- A obrigação acadêmica de registrar interação conversacional no MongoDB continua atendida pelos turnos, mesmo sem armazenar ali o resumo.
- A amostra fornecida confirma a granularidade de um documento por conversa; o nome físico aprovado para o array é `messages` (a amostra o chama de `mensagens`) e o campo `resumo` não deve ser persistido. Preservam-se os nomes atuais dos demais campos e `_id`; não duplicar a identidade como `session_id` sem consumidor comprovado.
- O Qdrant passa a ser o único armazenamento persistente do conteúdo do resumo; metadados operacionais mínimos poderão ser necessários, mas não podem reconstruir ou duplicar o texto do resumo no MongoDB.
- A decisão substitui a regra anterior documentada fora de `specs/` que mantinha uma cópia durável do resumo no MongoDB; a especificação aqui é a fonte de verdade para esta feature do serviço de IA.
- O título da conversa não é o resumo e seu armazenamento não foi alterado por esta decisão; seu contrato pode ser revisado separadamente.
- A exclusão explícita de conversa remove turnos do MongoDB e resumo do Qdrant. Uma política de retenção automática para conversas não excluídas não foi definida nesta feature e fica fora do escopo atual.
- A estratégia confirmada em alto nível é: mensagens identificáveis e ordenáveis; atualização idempotente de um ponto Qdrant por conversa com marcador de progresso; retries limitados e falhas esgotadas observáveis/reprocessáveis; reconciliação de conversas encerradas; serialização por conversa e proteção contra jobs atrasados após exclusão. Limites numéricos, mecanismo concreto de lease/claim e detalhes de agendamento/concorrência são decisões técnicas de implementação a serem registradas e testadas antes do cutover. Nenhum desses metadados autoriza persistir o texto do resumo no MongoDB.
