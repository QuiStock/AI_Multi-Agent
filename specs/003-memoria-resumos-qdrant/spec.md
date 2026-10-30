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
3. **Given** as coleções antigas de memória, **When** o novo fluxo for ativado, **Then** o histórico antigo será descartado e as novas coleções MongoDB e Qdrant começarão vazias, sem importar mensagens ou resumos.

## Clarifications

### Session 2026-10-01

- Q: Qual identificador representa o usuário nas novas coleções de memória e nas requisições? → A: O email obtido da claim `email` do JWT será a identidade canônica; requisições não enviarão `user_id`, e novas coleções MongoDB, payloads Qdrant e metadados de jobs/filas usarão email. Como as coleções serão criadas novamente, não será feito backfill de identidade de `user_id` para email.

### Session 2026-10-02 — conclusão do worker

- Q: O worker de resumo deve ser tratado como parte da feature 003, mesmo já
  existindo um processo parcial no código? → A: Sim. A implementação atual é
  evidência de estado parcial; a feature só será considerada concluída após
  validação do worker, concorrência, reconciliação, exclusão cross-store,
  provisionamento vazio e evidências operacionais.
- Q: O que é permitido persistir no job? → A: Somente metadados técnicos do
  job, identidade canônica, estado, tentativas, lease, agendamento, erro
  seguro e correlação. Nunca transcript, prompt, resumo ou saída bruta do
  modelo.
- Q: O que acontece quando uma conversa é retomada ou excluída enquanto o
  worker processa? → A: O job deve ser invalidado/superseded ou convergir para
  limpeza; nenhum worker atrasado pode reindexar o resumo de uma conversa
  ativa, deletando ou tombstonada.
- Q: O cutover deve importar o histórico antigo? → A: Não. O provisionamento
  deve validar os nomes exatos das novas coleções, criá-las vazias e exigir
  confirmação explícita antes de qualquer descarte físico.

### Estado da implementação do worker

O código atual contém scheduler, metadata de jobs MongoDB, relay/outbox, Redis
Streams, consumer group, lease/heartbeat por conversa, processamento
incremental no Qdrant, reconciliador periódico/manual, job de exclusão
cross-store e provisionador de coleções vazias. Isso ainda não encerra a
feature: `tasks.md` mantém pendentes os testes cross-store/concorrência e a
execução de cutover nos serviços alvo.

Os valores atualmente codificados — cinco tentativas máximas, backoff inicial
de dois segundos limitado a cinco minutos, lease padrão de cinco minutos e
leitura de até dez entradas por ciclo — são parâmetros propostos para o plano
e devem ser confirmados por teste e ambiente antes de serem tratados como SLO.

### Session 2026-10-02 — decisões operacionais adicionais

- Q: Onde o worker será executado? → A: Como serviço separado em produção e,
  inicialmente, como serviço separado dentro de um Docker Compose.
- Q: Quais parâmetros de retry/lease serão usados inicialmente? → A: Aceitar
  os valores atualmente codificados como baseline: cinco tentativas, backoff de
  dois segundos até cinco minutos, lease de cinco minutos e lote de dez
  entradas, sujeitos à validação de integração.
- Q: Como a reconciliação será disparada? → A: Um ciclo periódico no processo
  do worker, com comando one-shot/manual para evidência e reprocessamento. O
  intervalo exato fica para o plano.
- Q: A exclusão de conversa poderá ser implementada como operação pública? →
  A: Sim. O contrato será uma operação autenticada, idempotente e protegida
  por ownership; a limpeza cross-store continua assíncrona e coordenada pelo
  worker.
- Q: Quais dependências ficarão locais na primeira validação? → A: Redis
  ficará local no Docker Compose. MongoDB e Qdrant serão acessados pelas URLs
  configuradas em `.env`; nenhum host ou URL será fixado na spec ou no código.
- Q: O que deve ser considerado no cutover? → A: Os valores de URL, nomes de
  coleção e credenciais podem mudar por ambiente; o procedimento deve ler
  configuração, validar o alvo efetivo e nunca assumir valores do ambiente
  anterior.

### Session 2026-09-30

- Q: Onde o resumo conversacional deve permanecer persistido? → A: Somente no Qdrant; não manter cópia do conteúdo do resumo no MongoDB.
- Q: Como os registros conversacionais serão organizados no MongoDB? → A: Um documento por conversa; as mensagens são acrescentadas ao array físico `messages` (o exemplo original o chamou de `mensagens`), e cada turno é representado pelas mensagens correspondentes do usuário e do assistente. Esta resposta substitui a interpretação anterior de um documento por turno.
- Q: Como tratar o histórico e os resumos das coleções antigas? → A: Descartar o histórico antigo; recriar as coleções MongoDB e Qdrant vazias, sem migração ou backfill de mensagens e resumos.
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
- O novo cutover não deve importar dados antigos das coleções descartadas.
- A recuperação semântica não pode expor resumo de outro usuário nem tratar payload enviado pelo cliente como autorização.

## Requirements

### Functional Requirements

- **FR-001**: O serviço MUST persistir cada conversa em um único documento MongoDB associado ao usuário e acrescentar as mensagens ao array físico `messages`, preservando a ordem; um turno é formado pelas mensagens correspondentes do usuário e do assistente, não por um documento MongoDB separado.
- **FR-002**: O serviço MUST gerar e manter o conteúdo persistido do resumo conversacional somente no Qdrant.
- **FR-003**: O serviço MUST recuperar e atualizar o resumo no Qdrant sem depender de uma cópia do texto do resumo no MongoDB.
- **FR-004**: O MongoDB MUST NOT receber nem manter campos ou documentos cujo conteúdo seja o resumo conversacional. Nenhum resumo legado será importado para as novas coleções.
- **FR-005**: Turnos e resumos MUST permanecer isolados pelo email canônico e pela conversa, usando a identidade obtida pelo servidor do JWT para leituras e gravações protegidas; `user_id` não será o identificador de usuário persistido.
- **FR-006**: Falha de persistência do resumo no Qdrant MUST NOT causar fallback que grave o conteúdo do resumo no MongoDB.
- **FR-007**: O fluxo MUST permitir detectar e reparar divergência entre turnos duráveis no MongoDB e o resumo indexado no Qdrant sem criar uma segunda cópia persistente do resumo no MongoDB.
- **FR-008**: Na transição para o novo fluxo, o serviço MUST recriar as coleções de memória MongoDB e Qdrant vazias e MUST NOT importar mensagens, resumos ou marcadores de progresso das coleções antigas.
- **FR-009**: Ao encerrar uma conversa, o serviço MUST concluir o encerramento sem aguardar a geração ou atualização do resumo no Qdrant; o processamento ocorre em segundo plano e deve permitir novas tentativas e reconciliação em caso de falha.
- **FR-010**: Quando uma conversa for excluída por solicitação autorizada, o serviço MUST remover seus turnos do MongoDB e o resumo correspondente do Qdrant.
- **FR-011**: Cada mensagem MUST ter identidade estável e ordenação recuperável dentro da conversa para permitir deduplicação de gravações e determinar quais mensagens já foram incorporadas ao resumo.
- **FR-012**: A atualização do resumo MUST ser idempotente por conversa: repetir um job já aplicado não pode criar outro ponto lógico nem reduzir o progresso de mensagens resumidas.
- **FR-013**: Falhas temporárias na atualização do Qdrant MUST gerar retries limitados; falhas que esgotarem as tentativas MUST permanecer observáveis e passíveis de reprocessamento.
- **FR-014**: O serviço MUST reconciliar conversas encerradas comparando a mensagem mais recente persistida no MongoDB com o progresso indicado no Qdrant e agendar correção quando o ponto estiver ausente ou atrasado.
- **FR-015**: Atualizações de resumo da mesma conversa MUST ser serializadas ou protegidas contra gravação fora de ordem; jobs pendentes ou atrasados MUST NOT recriar o ponto de resumo após a exclusão da conversa.
- **FR-016**: O email autenticado MUST ser usado como identificador do usuário nos novos documentos de conversa MongoDB, jobs duráveis, payloads Qdrant e filtros de isolamento. O histórico antigo será descartado; não será feito backfill nem preservação das coleções antigas.

### Requisitos específicos de conclusão do worker

- **FR-WRK-001**: O worker MUST executar fora do processo HTTP, com composição
  própria de MongoDB, Redis, Qdrant e modelo, e MUST encerrar com shutdown
  controlado sem confirmar jobs não concluídos.
- **FR-WRK-002**: Cada job MUST possuir estado observável entre `queued`,
  `processing`, `completed`, `failed` e `superseded`; transições inválidas
  MUST ser rejeitadas ou permanecer sem efeito.
- **FR-WRK-003**: A reivindicação de job MUST usar lease renovável e a
  atualização de uma conversa MUST usar coordenação por conversa; antes do
  upsert Qdrant, o worker MUST revalidar lease, tombstone/status e watermark.
- **FR-WRK-004**: Se o worker perder a lease, sofrer timeout após o upsert ou
  encontrar falha transitória, o resultado MUST convergir sem duplicar o
  ponto, regredir watermark ou confirmar prematuramente o job.
- **FR-WRK-005**: O reconciliador MUST ser reiniciável e idempotente, detectar
  ponto ausente, watermark atrasado, ponto órfão e progresso inconsistente, e
  reenfileirar ou limpar sem copiar o resumo para MongoDB.
- **FR-WRK-006**: A exclusão MUST marcar a conversa como não legível antes da
  limpeza, manter tombstone/estado suficiente para impedir ressurreição e
  convergir para ausência tanto no MongoDB quanto no Qdrant.
- **FR-WRK-007**: O provisionamento MUST criar as novas coleções com índices
  necessários e email como identidade, verificar que estão vazias e MUST NOT
  importar histórico antigo; alvos físicos ambíguos devem interromper o
  procedimento.
- **FR-WRK-008**: A feature MUST possuir testes unitários, cross-store e de
  integração para worker concorrente, retry, lease perdida, retomada,
  exclusão, reconciliação, cutover vazio e isolamento por email.
- **FR-WRK-009**: A API MUST oferecer uma operação autenticada e idempotente
  para solicitar a exclusão de uma conversa própria, sem aceitar `email` ou
  outro proprietário no body/query; a operação deve iniciar a limpeza
  cross-store e retornar estado/correlação sem aguardar toda a remoção física.

### Contrato HTTP proposto para exclusão

Esta operação passa a fazer parte do escopo da feature, mas seus nomes finais
devem ser alinhados ao router HTTP existente no plano:

- **Método/rota**: `DELETE /api/v1/conversations/{conversation_id}`.
- **Ator/autenticação**: usuário autenticado por Bearer JWE; o email vem da
  identidade validada, nunca do body ou query.
- **Request**: sem body obrigatório; `conversation_id` é o único identificador
  de recurso na rota.
- **Sucesso**: `202 Accepted` com `conversation_id`, `request_id`/`trace_id` e
  `status: "deleting"` ou `"accepted"`.
- **Repetição**: repetir a mesma solicitação própria deve ser segura e não
  recriar job ou tombstone; uma conversa já ausente pode retornar o mesmo
  resultado idempotente ou `404`, conforme a decisão de UX do plano.
- **Isolamento**: recurso inexistente ou pertencente a outro usuário não deve
  revelar dados de terceiros; a resposta deve seguir o padrão seguro da API.
- **Falhas**: credencial inválida retorna `401`; falha de dependência que
  impeça persistir a solicitação retorna erro controlado; falha posterior de
  limpeza permanece no job observável e reprocessável.
- **Efeito**: primeiro tornar a conversa não legível e persistir o estado/job
  de limpeza; depois remover o ponto Qdrant e o documento MongoDB de forma
  convergente.

### Key Entities

- **Conversa**: agrupamento lógico de interações de um usuário, identificado por um identificador estável e associado ao email canônico do usuário.
- **Turno**: interação do usuário e do assistente representada por mensagens relacionadas dentro do array `messages` do documento da conversa.
- **Mensagem**: elemento de `messages` com identificador estável e posição/ordem estável dentro da conversa.
- **Documento de conversa**: documento MongoDB único por conversa, com metadados e o array ordenado `messages`; não contém o texto do resumo.
- **Resumo conversacional**: representação derivada dos turnos, persistida somente no Qdrant e associada à conversa e ao email canônico do usuário.
- **Progresso do resumo**: metadado no ponto Qdrant que identifica até qual mensagem/ordem o resumo considera, sem guardar texto de resumo no MongoDB.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Em todos os testes de persistência, uma conversa possui um único documento MongoDB e suas mensagens são recuperadas em ordem após encerramento e retomada.
- **SC-002**: Em todos os testes de gravação e atualização de resumo, seu conteúdo persistido está disponível no Qdrant e ausente dos dados persistidos no MongoDB.
- **SC-003**: Em todos os testes de isolamento, um usuário não consegue recuperar turnos ou resumos associados a outro usuário.
- **SC-004**: Após o cutover, as novas coleções não contêm mensagens ou resumos importados das coleções antigas; a nova memória começa vazia.
- **SC-005**: Falhas e retries de atualização permitem convergir o resumo do Qdrant com os turnos de origem sem duplicar turnos nem persistir resumo no MongoDB.
- **SC-006**: O encerramento de uma conversa permanece concluído mesmo quando a atualização do resumo ainda está pendente ou falha temporariamente.
- **SC-007**: Após excluir uma conversa, nenhum de seus turnos permanece no MongoDB e seu resumo não pode mais ser recuperado do Qdrant.
- **SC-008**: Reexecutar uma atualização concluída não duplica nem regride o ponto Qdrant, e atualizações repetidas convergem para a mensagem mais recente da conversa.
- **SC-009**: Uma conversa encerrada cujo resumo esteja ausente ou atrasado em relação ao MongoDB é identificada pela reconciliação e pode ser reprocessada sem duplicar mensagens.
- **SC-010**: Nenhum job atrasado recria o resumo de uma conversa após a exclusão ser concluída.
- **SC-011**: MongoDB, jobs e payloads/filtros Qdrant usam email como identidade do usuário desde a criação das novas coleções.
- **SC-012**: Novas coleções de memória persistem email como identidade desde a criação e não dependem de `user_id` legado.
- **SC-WRK-001**: Dois workers concorrentes processando a mesma conversa não
  produzem dois pontos lógicos nem regressão de watermark; o segundo aguarda,
  reprocessa ou termina de forma observável.
- **SC-WRK-002**: Uma exclusão concorrente ou concluída impede que qualquer job
  atrasado recrie o ponto Qdrant e termina com ausência verificável nos dois
  stores.
- **SC-WRK-003**: Uma execução do reconciliador pode ser interrompida e
  reiniciada sem duplicar jobs, resumos ou exclusões e corrige ponto ausente,
  atrasado ou órfão.
- **SC-WRK-004**: O cutover validado cria coleções novas vazias, com índices
  exigidos e identidade por email, sem importar histórico e sem atingir alvo
  físico não confirmado.
- **SC-WRK-005**: Uma solicitação autenticada de exclusão própria retorna uma
  resposta idempotente e, após a convergência do worker, não deixa conversa no
  MongoDB nem ponto correspondente no Qdrant.

## Assumptions

- A obrigação acadêmica de registrar interação conversacional no MongoDB continua atendida pelos turnos, mesmo sem armazenar ali o resumo.
- A amostra fornecida confirma a granularidade de um documento por conversa; o nome físico aprovado para o array é `messages` (a amostra o chama de `mensagens`) e o campo `resumo` não deve ser persistido. Preservam-se os nomes atuais dos demais campos e `_id`; não duplicar a identidade como `session_id` sem consumidor comprovado.
- O Qdrant passa a ser o único armazenamento persistente do conteúdo do resumo; metadados operacionais mínimos poderão ser necessários, mas não podem reconstruir ou duplicar o texto do resumo no MongoDB.
- A decisão substitui a regra anterior documentada fora de `specs/` que mantinha uma cópia durável do resumo no MongoDB; a especificação aqui é a fonte de verdade para esta feature do serviço de IA.
- O histórico antigo de mensagens e resumos será descartado quando as coleções forem recriadas; não haverá migração/backfill para as novas coleções.
- O título da conversa não é o resumo e seu armazenamento não foi alterado por esta decisão; seu contrato pode ser revisado separadamente.
- A exclusão explícita de conversa remove turnos do MongoDB e resumo do Qdrant. Uma política de retenção automática para conversas não excluídas não foi definida nesta feature e fica fora do escopo atual.
- A estratégia confirmada em alto nível é: mensagens identificáveis e ordenáveis; atualização idempotente de um ponto Qdrant por conversa com marcador de progresso; retries limitados e falhas esgotadas observáveis/reprocessáveis; reconciliação de conversas encerradas; serialização por conversa e proteção contra jobs atrasados após exclusão. Limites numéricos, mecanismo concreto de lease/claim e detalhes de agendamento/concorrência são decisões técnicas de implementação a serem registradas e testadas antes do cutover. Nenhum desses metadados autoriza persistir o texto do resumo no MongoDB.
- Email obtido do JWT é a identidade canônica nas novas coleções MongoDB, Qdrant e metadados de jobs. As coleções antigas e seu histórico serão descartados; as coleções novas começam vazias e não recebem backfill.
