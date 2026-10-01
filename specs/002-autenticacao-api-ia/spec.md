# Feature Specification: Autenticação e identidade na API de IA

**Feature Branch**: `002-autenticacao-api-ia`
**Created**: 2026-09-30
**Status**: Draft
**Input**: User description: “Criar um sistema de autenticação de usuário antes de avançar com o funcionamento das demais capacidades da IA; decidir o limite correto da autenticação e impedir que a identidade seja aceita apenas por dados enviados pelo cliente.”

## User Scenarios & Testing

### User Story 1 - Usuário autenticado acessa suas conversas (Priority: P1)

Como usuário do Quistock, quero acessar o serviço de IA com minha identidade validada para usar conversas sem que outro usuário possa ler, retomar, encerrar ou alterar meu histórico.

**Why this priority**: O serviço recebe atualmente identificadores de usuário nas requisições. A autenticação é pré-requisito para ferramentas e funcionalidades que consultem dados protegidos.

**Independent Test**: Enviar requisições com credencial válida, ausente, inválida, expirada e pertencente a outra identidade; verificar o acesso e o isolamento entre usuários.

**Acceptance Scenarios**:

1. **Given** uma credencial válida, **When** o usuário acessa uma conversa própria, **Then** a operação respeita a identidade validada.
2. **Given** uma credencial ausente, inválida ou expirada, **When** uma rota protegida é chamada, **Then** o acesso é recusado antes de iniciar o processamento da conversa.
3. **Given** uma conversa pertencente a outra identidade, **When** o usuário tenta listá-la, retomá-la, encerrá-la ou enviar uma mensagem nela, **Then** nenhum dado ou operação dessa conversa é disponibilizado.

### User Story 2 - Identidade confiável é propagada às capacidades da IA (Priority: P1)

Como responsável pelo serviço, quero que as capacidades recebam uma identidade estabelecida por uma fronteira confiável para que nenhuma tool ou agente use um identificador arbitrário enviado no corpo da requisição.

**Why this priority**: O Product Workflow futuro consultará dados comerciais e precisa respeitar autorização e escopo de loja definidos pelo servidor.

**Independent Test**: Alterar identificadores enviados pelo cliente mantendo a mesma credencial e confirmar que autorização e persistência continuam vinculadas à identidade validada.

**Acceptance Scenarios**:

1. **Given** uma credencial válida, **When** uma requisição contém um user_id diferente no payload, **Then** o user_id do payload não substitui a identidade autenticada.
2. **Given** uma operação protegida executada por agente ou tool, **When** ela precisa da identidade do usuário, **Then** recebe somente a identidade e os escopos estabelecidos pela fronteira confiável.
3. **Given** uma falha de autenticação, **When** o pedido é rejeitado, **Then** nenhum dado de credencial ou detalhe interno é exposto na resposta ou em logs comuns.

### Edge Cases

- Credencial malformada, expirada, revogada ou assinada por emissor não confiável.
- Token válido sem os dados de identidade necessários para localizar o proprietário da conversa.
- Identificador da conversa inexistente ou de outro usuário; a resposta não deve revelar dados de terceiros.
- Dependência de autenticação indisponível ou falha na validação.
- Cliente envia identidade duplicada ou contraditória em body, query ou headers.
- Rotas de saúde e operações internas não acessíveis ao usuário não devem ser ampliadas por acidente ao proteger as rotas de conversa.

## Requirements

### Functional Requirements

- **FR-001**: Todas as operações de conversa protegidas MUST exigir uma credencial válida antes de iniciar o grafo ou executar uma operação de memória.
- **FR-002**: O serviço MUST estabelecer a identidade do usuário por uma fronteira confiável; um user_id fornecido pelo cliente MUST NOT substituir ou ampliar a identidade autenticada.
- **FR-003**: A autorização MUST limitar leitura, listagem, retomada, mensagem e encerramento às conversas da identidade autenticada.
- **FR-004**: A identidade validada MUST ser propagada de forma consistente para persistência, memória e capacidades protegidas.
- **FR-005**: Falha ou ausência de autenticação MUST resultar em rejeição segura, sem iniciar processamento protegido nem revelar dados de terceiros.
- **FR-006**: Falhas de autenticação MUST ser registradas sem armazenar credenciais, tokens completos, prompts privados ou conteúdo sensível em telemetria comum.
- **FR-007**: A autenticação MUST ocorrer antes da execução do grafo; um nó do grafo não será a autoridade que estabelece a identidade.
- **FR-008**: A API FastAPI de IA MUST validar o token recebido por meio da API/serviço de autenticação oficialmente definido pelo Quistock. O emissor concreto, protocolo, claims, identificador canônico e parâmetros criptográficos permanecem em aberto e MUST ser revisados e especificados antes da implementação da autenticação.
- **FR-009**: O escopo desta feature MUST proteger as operações de conversa da API de IA; login, emissão de credenciais e autorização de ferramentas de negócio ficam fora do escopo, salvo decisão explícita nesta especificação.

### Key Entities

- **Credencial de acesso**: prova apresentada pelo chamador e sujeita a validação de autenticidade, validade e emissor.
- **Identidade autenticada**: identidade estabelecida pelo serviço após validação; não pode ser sobrescrita por dados do payload.
- **Conversa**: recurso de memória pertencente a uma única identidade de usuário.
- **Escopo de autorização**: conjunto de recursos que a identidade pode acessar; escopos de loja e papéis comerciais precisam ser definidos para features futuras.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% das rotas de conversa protegidas recusam credenciais ausentes, inválidas ou expiradas antes do processamento do grafo.
- **SC-002**: Em testes de isolamento, nenhum usuário consegue ler, retomar, listar, encerrar ou alterar conversa pertencente a outro usuário.
- **SC-003**: Alterar user_id no payload não altera a identidade nem o escopo efetivo da requisição.
- **SC-004**: Falhas de autenticação não deixam tokens completos ou segredos nos logs comuns e não produzem efeitos de persistência.
- **SC-005**: Antes da implementação, existe um contrato revisado que identifica o serviço de autenticação, o protocolo de validação, os dados de identidade confiáveis e o comportamento em falhas.

## Assumptions

- O aplicativo já possui um fluxo de login; esta feature trata a confiança da API de IA na identidade, não a criação de contas nem uma nova tela de login.
- As rotas de conversa são protegidas; endpoints estritamente operacionais/health podem ter política separada a ser confirmada.
- A identidade validada deve chegar ao grafo antes de ferramentas protegidas. A validação não será delegada ao router ou a outro agente.
- Decisão confirmada em alto nível: haverá uma API/serviço de autenticação do Quistock, fora da implementação deste projeto, e a API FastAPI de IA deverá validar o token recebido antes do processamento protegido. A identidade não será aceita apenas porque veio encaminhada no payload ou em cabeçalho não autenticado.
- Em aberto para revisão antes da implementação completa: qual serviço emite/valida o token, protocolo de integração, claims obrigatórios, identificador canônico do usuário, parâmetros criptográficos, configuração de chaves e comportamento diante de indisponibilidade. Não se assume que a API Spring comercial seja a emissora.
- A autorização de conversas do MVP usa propriedade por usuário. Papéis e escopo de loja necessários ao Product Workflow serão especificados junto ao contrato de dados e não serão inferidos aqui.
