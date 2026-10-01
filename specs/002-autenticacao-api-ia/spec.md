# Feature Specification: Autenticação e identidade na API de IA

**Feature Branch**: `002-autenticacao-api-ia`
**Created**: 2026-09-30
**Status**: Draft
**Input**: User description: “Criar um sistema de autenticação de usuário antes de avançar com o funcionamento das demais capacidades da IA; decidir o limite correto da autenticação e impedir que a identidade seja aceita apenas por dados enviados pelo cliente.”

## User Scenarios & Testing

### User Story 1 - Usuário autenticado acessa suas conversas (Priority: P1)

Como usuário do Quistock, quero acessar o serviço de IA com minha identidade validada para usar conversas sem que outro usuário possa ler, retomar, encerrar ou alterar meu histórico.

**Why this priority**: O serviço recebe atualmente identificadores de usuário nas requisições. A autenticação é pré-requisito para ferramentas e funcionalidades que consultem dados protegidos.

**Independent Test**: Enviar requisições com JWT Bearer válido, ausente, inválido ou indecriptável, email associado ou não a uma conta, papel de gerente regional e falha temporária do PostgreSQL; verificar status e ausência de processamento indevido. Tokens expirados são barrados antes de chegar à API.

**Acceptance Scenarios**:

1. **Given** um JWT válido cujo email corresponde a uma conta, **When** o usuário acessa uma conversa própria, **Then** a operação usa o email como identidade do usuário e como chave de isolamento.
2. **Given** um Bearer Token ausente, inválido ou que não possa ser descriptografado, **When** uma rota protegida é chamada, **Then** a API retorna `401` antes de iniciar o processamento da conversa. Tokens expirados não chegam à API.
3. **Given** uma conversa pertencente a outra identidade, **When** o usuário tenta listá-la, retomá-la, encerrá-la ou enviar uma mensagem nela, **Then** nenhum dado ou operação dessa conversa é disponibilizado.
4. **Given** que o email não exista em `user_account`, **When** a identidade é validada, **Then** a API retorna `401` e não inicia o processamento protegido.
5. **Given** que o registro correspondente tenha `role_id = 1` (gerente regional), **When** esse usuário chama uma rota protegida, **Then** a API retorna `403` e não inicia o processamento protegido.
6. **Given** que o PostgreSQL apresente instabilidade temporária durante a validação, **When** uma rota protegida é chamada, **Then** a API retorna `500` e não inicia o processamento protegido.

### User Story 2 - Identidade confiável é propagada às capacidades da IA (Priority: P1)

Como responsável pelo serviço, quero que as capacidades recebam o email estabelecido pela claim do JWT para que nenhuma tool ou agente use uma identidade arbitrária enviada pelo cliente.

**Why this priority**: O Product Workflow futuro consultará dados comerciais e precisa respeitar autorização e escopo de loja definidos pelo servidor.

**Independent Test**: Omitir qualquer identificador de usuário do payload e confirmar que autorização e persistência usam o email obtido do JWT.

**Acceptance Scenarios**:

1. **Given** uma credencial válida e email correspondente a uma conta, **When** uma requisição chega sem `user_id`, **Then** a API estabelece o email do JWT como identidade e continua a validação de papel.
2. **Given** uma operação protegida executada por agente ou tool, **When** ela precisa da identidade do usuário, **Then** recebe somente o email estabelecido pelo JWT e os escopos derivados pelo servidor.
3. **Given** uma falha de autenticação, **When** o pedido é rejeitado, **Then** nenhum dado de credencial ou detalhe interno é exposto na resposta ou em logs comuns.

### Edge Cases

- Credencial malformada ou que não possa ser descriptografada.
- Token válido sem os dados de identidade necessários para localizar o proprietário da conversa.
- Identificador da conversa inexistente ou de outro usuário; a resposta não deve revelar dados de terceiros.
- PostgreSQL temporariamente indisponível ou com falha durante a consulta da identidade.
- Conta autenticada com papel de gerente regional, que não pode acessar as rotas protegidas desta feature.
- Cliente inclui `user_id` em body ou query; esse campo não pode influenciar a identidade autenticada.
- Rotas de saúde e operações internas não acessíveis ao usuário não devem ser ampliadas por acidente ao proteger as rotas de conversa.

## Requirements

### Functional Requirements

- **FR-001**: Todas as operações de conversa protegidas MUST exigir uma credencial válida antes de iniciar o grafo ou executar uma operação de memória.
- **FR-002**: O serviço MUST estabelecer a identidade exclusivamente pelo email obtido da claim `email` do JWT; a requisição MUST NOT precisar enviar `user_id` nem outro identificador de usuário para estabelecer a identidade.
- **FR-003**: A autorização MUST limitar leitura, listagem, retomada, mensagem e encerramento às conversas da identidade autenticada.
- **FR-004**: A identidade validada MUST ser propagada de forma consistente para persistência, memória e capacidades protegidas.
- **FR-005**: Falha ou ausência de autenticação MUST resultar em rejeição segura, sem iniciar processamento protegido nem revelar dados de terceiros.
- **FR-006**: Falhas de autenticação MUST ser registradas sem armazenar credenciais, tokens completos, prompts privados ou conteúdo sensível em telemetria comum.
- **FR-007**: A autenticação MUST ocorrer antes da execução do grafo; um nó do grafo não será a autoridade que estabelece a identidade.
- **FR-008**: A API FastAPI de IA MUST receber no cabeçalho `Authorization` como Bearer Token um JWT criptografado (JWE) emitido por uma API externa (fora do escopo de implementação desta feature), com `alg=RSA-OAEP-256` e `enc=A256GCM`, e descriptografá-lo usando a chave privada RSA configurada por ambiente para obter exclusivamente a claim `email`. A chave RSA MUST ter no mínimo 2048 bits. O emissor externo deverá criptografar com a chave pública correspondente; a API externa não será implementada nem integrada por chamadas próprias nesta feature. A biblioteca de processamento será `jwcrypto`. Durante rotação com mais de uma chave privada ativa, o JWE MUST incluir `kid` no cabeçalho protegido para selecionar a chave correspondente; `kid` não é uma claim e não será usado como dado de identidade. A API consultará diretamente `user_account.email` e `user_account.role_id` no PostgreSQL. A credencial PostgreSQL da API de IA MUST ter somente permissões de leitura necessárias para essa consulta, sem escrita, DDL ou concessão de privilégios. Segredos reais MUST NOT ser incluídos no controle de versão.
- **FR-009**: O escopo desta feature MUST proteger as operações de conversa da API de IA; login, emissão de credenciais e autorização de ferramentas de negócio ficam fora do escopo, salvo decisão explícita nesta especificação.
- **FR-010**: Se o email da claim `email` não corresponder a uma linha em `user_account`, a API MUST retornar `401` antes do processamento protegido.
- **FR-011**: O email extraído da claim `email` MUST ser a identidade canônica propagada ao fluxo e usada para autorizar, persistir, buscar e isolar os dados do usuário; a API MUST NOT exigir ou usar `user_id` enviado pelo cliente como identidade.
- **FR-012**: A API MUST retornar `401` quando o Bearer Token estiver ausente, inválido ou não puder ser descriptografado para obter a claim `email`, antes de iniciar o processamento protegido. A API não recebe nem valida tokens expirados: a camada emissora/de encaminhamento garante que somente tokens ainda válidos cheguem à API.
- **FR-013**: Se houver instabilidade temporária ou indisponibilidade do PostgreSQL durante a consulta necessária para validar a identidade, a API MUST retornar `500` sem iniciar o processamento protegido.
- **FR-014**: Se a linha de `user_account` correspondente ao email tiver `role_id = 1` (gerente regional), a API MUST retornar `403` antes do processamento protegido.
- **FR-015**: As novas coleções/documentos de memória MongoDB, payloads de usuário no Qdrant e metadados de jobs/filas MUST usar o email como identificador de usuário; não haverá backfill de identidade `user_id` para email nessas novas coleções.
- **FR-016**: Requisições de conversa MUST NOT exigir `user_id` no body ou query para identificar o usuário; essa identidade é obtida do JWT.
- **FR-017**: O endpoint `/health` MUST informar se a API está disponível e verificar a disponibilidade de PostgreSQL, MongoDB, Redis, Qdrant e dos provedores de modelos usados pelo chatbot (Gemini e Groq). Se todas estiverem disponíveis, MUST retornar HTTP `200` com `{"status":"ok","checks":{"api":"ok","postgresql":"ok","mongodb":"ok","redis":"ok","qdrant":"ok","gemini":"ok","groq":"ok"}}`. Se qualquer dependência estiver indisponível, MUST retornar HTTP `500`, `status: "error"` e identificar em `checks` cada serviço como `"ok"` ou `"unavailable"`, sem expor segredos ou detalhes internos.
- **FR-018**: A credencial usada pela API de IA para consultar PostgreSQL MUST ser exclusiva do serviço e somente de leitura; o serviço não pode usar essa credencial para alterar dados ou schema.

### Key Entities

- **Credencial de acesso**: JWT criptografado (JWE) com `alg=RSA-OAEP-256` e `enc=A256GCM`, enviado no cabeçalho `Authorization` como Bearer Token e processado pela biblioteca `jwcrypto` para obter exclusivamente a claim `email`. A chave privada RSA (mínimo 2048 bits) é fornecida por ambiente; o emissor usa a chave pública correspondente. Na rotação, `kid` protegido seleciona a chave; chaves antiga e nova convivem temporariamente. A emissão e a implementação da API externa estão fora do escopo.
- **Identidade autenticada**: email obtido da claim `email` e associado a uma linha de `user_account`; o próprio email é propagado como identidade canônica, sem exigir `user_id` do cliente.
- **Conversa**: recurso de memória pertencente a uma única identidade de usuário.
- **Escopo de autorização**: conjunto de recursos que a identidade pode acessar; escopos de loja e papéis comerciais precisam ser definidos para features futuras.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% das rotas de conversa protegidas retornam `401` para Bearer Tokens ausentes, inválidos ou indecriptáveis, ou email sem conta, antes do processamento do grafo; tokens expirados são barrados antes de chegar à API.
- **SC-002**: Em testes de isolamento, nenhum usuário consegue ler, retomar, listar, encerrar ou alterar conversa pertencente a outro usuário.
- **SC-003**: 100% das rotas de conversa estabelecem a identidade e o isolamento pelo email do JWT sem exigir `user_id` no payload ou query.
- **SC-004**: Falhas de autenticação não deixam tokens completos ou segredos nos logs comuns e não produzem efeitos de persistência.
- **SC-005**: Antes da implementação, existe um contrato revisado que identifica o formato e a validação da credencial, a relação de ownership do acesso PostgreSQL, os dados de identidade confiáveis e o comportamento em falhas.
- **SC-006**: 100% das instabilidades temporárias do PostgreSQL durante a validação retornam `500` e não iniciam o processamento protegido.
- **SC-007**: 100% das contas com `role_id = 1` recebem `403` antes do processamento protegido.
- **SC-008**: Health informa disponibilidade da API e das dependências do chatbot no formato JSON acordado, sem iniciar processamento de conversa.
- **SC-009**: Toda nova persistência de memória identifica o usuário pelo email e não grava `user_id` como identidade.
- **SC-010**: `/health` retorna sucesso somente quando a API e todas as dependências verificadas estão disponíveis; falha em qualquer uma resulta em `500`.
- **SC-011**: A credencial PostgreSQL da API de IA não consegue executar operações de escrita ou DDL e só consulta as colunas necessárias à autenticação.

## Assumptions

- O aplicativo já possui um fluxo de login; esta feature trata a confiança da API de IA na identidade, não a criação de contas nem uma nova tela de login.
- As rotas de conversa são protegidas; `/health` é operacional e avalia prontidão da API e disponibilidade das dependências necessárias ao chatbot.
- A identidade validada deve chegar ao grafo antes de ferramentas protegidas. A validação não será delegada ao router ou a outro agente.
- Decisão confirmada: o JWT criptografado (JWE) chega no header `Authorization: Bearer` com `alg=RSA-OAEP-256` e `enc=A256GCM`; a API usa `jwcrypto` e a chave privada RSA de `.env` para obter exclusivamente `email`, consulta `user_account.email` e propaga o email como identidade. O emissor usa a chave pública correspondente. A API não recebe nem compara `user_id`. A API externa de autenticação não será implementada nem chamada pela API de IA nesta feature.
- Decisões confirmadas: token ausente/inválido/indecriptável ou email sem correspondência retornam `401`; tokens expirados são barrados antes de chegar à API; `role_id = 1` identifica gerente regional e retorna `403`; instabilidade temporária do PostgreSQL retorna `500`. Nenhum desses casos inicia o processamento protegido.
- Decisão confirmada: email será a única identidade de usuário nas novas coleções MongoDB e demais metadados/payloads de memória. Não haverá migração de `user_id` para email nessas novas coleções.
- Decisão confirmada: `/health` verifica PostgreSQL, MongoDB, Redis, Qdrant, Gemini e Groq; qualquer dependência indisponível resulta em `500`.
- Decisão confirmada: não haverá backfill de identidade nas novas coleções de memória, que serão criadas usando email desde o início.
- Decisão confirmada: a credencial da API de IA para PostgreSQL terá somente leitura e será limitada às consultas de identidade; não terá escrita ou DDL.
- Decisão confirmada: o histórico das coleções antigas será descartado; as coleções MongoDB e Qdrant serão recriadas vazias para o novo fluxo, sem migração de mensagens ou resumos antigos.
- Decisão confirmada: a API de IA manterá conexão e credencial próprias, exclusivas e somente de leitura para consultar `user_account.email` e `role_id`; a API Spring permanece proprietária do schema e deve comunicar mudanças que afetem essa consulta. A API de IA não fará escrita, DDL, migração nem concessão de privilégios.
- Decisão confirmada: a chave de descriptografia JWE ficará em `.env`, que é ignorado pelo Git; `.env.example` terá somente o nome da variável e um placeholder. A API usará somente a claim `email`; nenhum outro claim será consumido.
- Decisão confirmada: rotação por `kid` no cabeçalho protegido do JWE. O emissor passa a cifrar com a chave pública nova; durante a janela de transição, a API mantém disponíveis a chave privada nova e a anterior e seleciona pela `kid`. A chave anterior só pode ser retirada depois de o emissor confirmar a troca e transcorrer o maior período em que um token cifrado com ela ainda possa ser encaminhado à API. Em comprometimento confirmado, a chave afetada deve ser revogada imediatamente, mesmo que isso invalide tokens ainda cifrados com ela. O conteúdo/valores do `.env` são responsabilidade do operador e não serão escritos ou versionados nesta feature. A API parte da garantia de que tokens expirados não chegam até ela; não é responsabilidade desta feature validar expiração. Login, emissão do token e implementação da API externa permanecem fora desta feature.
- A autorização de conversas do MVP usa propriedade por usuário. Papéis e escopo de loja necessários ao Product Workflow serão especificados junto ao contrato de dados e não serão inferidos aqui.

## Clarifications

### Session 2026-10-01
- Q: Quem deve ser responsável por manter o acesso da API de IA à tabela `user_account`? → A: A API de IA mantém conexão e credencial próprias somente de leitura; a API Spring permanece responsável pelo schema e por comunicar mudanças.
- Q: Para esta feature, devemos definir agora se o token é criptografado ou assinado, ou deixar essa escolha aberta até a revisão técnica antes da implementação? → A: O token recebido é um JWT criptografado (JWE); a API de IA o descriptografa para extrair `email`, deixando algoritmos e ciclo de vida da chave para revisão antes da implementação.
- Q: A API de IA deve validar a expiração do JWT? → A: Não. Tokens expirados são barrados antes de chegar à API; ela recebe tokens válidos e não implementa validação de expiração.
- Q: Qual formato deve retornar `/health` quando a API e todas as dependências estão prontas ou quando alguma está indisponível? → A: HTTP `200` com `status: "ok"` e todos os checks como `"ok"`; HTTP `500` com `status: "error"` e o check indisponível marcado `"unavailable"`, sem detalhes sensíveis.
- Q: Onde ficará a chave JWE e quais claims a API consumirá? → A: A chave fica em `.env` e a API usará somente a claim `email`, sem consumir outras claims.
- Q: Quais parâmetros criptográficos e biblioteca serão usados para o JWE? → A: `RSA-OAEP-256` para proteção da chave, `A256GCM` para criptografia autenticada do conteúdo e biblioteca Python `jwcrypto`.
- Q: Como será feita a rotação da chave JWE? → A: Usar `kid` no cabeçalho protegido; a API mantém a chave nova e a anterior durante a transição, retirando a anterior após a janela em que tokens antigos ainda podem chegar. Em caso de comprometimento, revogação imediata. O operador é responsável pelos valores de `.env`.
