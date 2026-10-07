# Feature Specification: Clarify da integração A2A

**Feature Branch**: `004-a2a-clarify`

**Created**: 2026-10-02

**Status**: Clarify

**Input**: decisão de iniciar a especificação da rota A2A antes de qualquer implementação.

## Objetivo

Fechar o escopo técnico mínimo da integração Agent2Agent (A2A) do Quistock,
separando decisões confirmadas, propostas e perguntas abertas. Esta etapa não
ativa rota, peer, card, dependência ou tarefa de implementação.

## Clarificações registradas — 2026-10-02

- O Quistock deverá atuar nos dois papéis: publicar seu próprio serviço A2A e
  consumir outro sistema A2A.
- O objetivo é disponibilizar o sistema Quistock como uma fachada A2A, e não
  expor diretamente cada executor interno. O AgentCard poderá anunciar várias
  skills do sistema; a entrada será roteada internamente para os agentes e
  guardrails permitidos.
- A integração de referência será uma interação externa existente, mas o
  primeiro ciclo poderá usar um mock local para validar o contrato.
- A versão A2A 1.0.0, REST/JSON e chamada síncrona foram aceitas como escopo
  inicial. Streaming, push e tarefas longas permanecem fora do MVP.
- O AgentCard inicial será público, mínimo e não exigirá assinatura digital no
  mock.
- O primeiro card anunciará as skills públicas `faq` e `product_flow`. A skill
  `product_flow` será mapeada internamente para a rota/capacidade existente
  `product_workflow`, preservando o vocabulário interno do código.
- O peer de referência inicial será chamado `mock_external_agent`.
- A resposta remota somente poderá contribuir como evidência quando trouxer a
  fonte original verificável.
- Foram aceitos os cenários acadêmicos de sucesso grounded e falha segura, e a
  proposta inicial de retry limitado.

### Explicação simples do AgentCard

Um `AgentCard` é o “cartão de visita técnico” de um sistema A2A. Ele é um JSON
que informa a outro sistema:

- quem é o agente e qual versão está publicada;
- qual URL deve ser chamada;
- qual versão e transporte A2A são suportados;
- quais capacidades/skills podem ser solicitadas;
- qual autenticação o cliente precisa usar.

Ele não contém o token, senha, email do usuário ou prompt privado. A opção
recomendada para o mock é um card público mínimo em
`/.well-known/agent-card.json`, com a URL, a skill e a indicação de bearer
token. O cliente lê o card e então chama a rota protegida. Em produção, um
card público pode continuar descrevendo o serviço, enquanto detalhes sensíveis
podem exigir autenticação adicional. Assinatura digital do card fica como
opção posterior, não como bloqueio do mock.

### Explicação simples da autenticação serviço a serviço

Há duas identidades diferentes na chamada:

1. a pessoa que usa o Quistock, autenticada pelo fluxo atual;
2. o sistema Quistock, autenticado perante o outro sistema A2A.

O JWE da pessoa não deve ser repassado automaticamente ao peer. Para o mock,
a opção mais simples é um bearer token próprio do ambiente, guardado em
variável de ambiente e enviado no header `Authorization`. Ele serve apenas
para o peer reconhecer que a chamada veio do Quistock.

Como evolução, esse bearer pode ser substituído por um token curto e assinado,
com `audience`, expiração e escopos. Assim, o contrato permanece o mesmo, mas
a credencial deixa de ser estática. O contexto autorizado da pessoa — email,
cargo, loja, `request_id` e `trace_id` — deve ser enviado separadamente em um
contexto assinado ou token delegado; nunca como campos que o modelo possa
alterar livremente.

#### Decisão em avaliação para o mock

É possível cadastrar o cliente dentro do próprio Quistock, por exemplo:

```text
client_id: mock_external_agent
base_url: http://mock-external-agent:9000
allowed_skills: [faq, product_flow]
trust_level: sandbox
```

Isso é uma boa prática para configuração e autorização local do peer, desde
que o registro não substitua a autenticação. O endpoint ainda deve verificar
que a chamada veio do `client_id` cadastrado por meio de uma chave/token de
ambiente, rede de desenvolvimento controlada ou mecanismo equivalente.

Não é uma boa prática considerar qualquer chamada autenticada apenas porque
as variáveis do cliente existem no Quistock. Sem uma prova mínima de origem,
qualquer processo que alcance a URL poderá se passar pelo peer e enviar outro
email, cargo, loja ou skill.

Para o mock, a opção mais simples é um segredo compartilhado de ambiente entre
Quistock e `mock_external_agent`. O Quistock usa o registro local para decidir
qual peer pode ser chamado e quais skills pode usar; o peer usa o mesmo segredo
para aceitar somente chamadas do Quistock. Em uma integração real, esse
segredo deve evoluir para credencial rotacionável ou token assinado.

## Estado atual

### Confirmado

- A rubrica acadêmica exige A2A para integração entre sistemas ou agentes
  externos (`docs/sdd/academic-constraints.md` no repositório Quistock).
- O roadmap registra `A2A-001` como direção confirmada: o router deverá ter
  uma nova rota para um sistema externo, mas card, peer, autenticação,
  payload, timeout e fallback ainda estão indefinidos
  (`docs/planejamento-multiagente-fastapi.md`).
- O runtime atual não possui integração A2A ativa. O grafo expõe somente a
  capacidade `faq` em `src/api/dependencies.py`; o router também pode terminar
  em esclarecimento ou fora de escopo.
- `src/agents/schemas/agent_card.py` modela cards locais do serviço, mas ainda
  não modela endpoint A2A, interfaces de transporte, esquemas de segurança,
  skills remotas ou assinatura do card. `src/agents/registry.py` não registra
  peer A2A.
- A autenticação de entrada da API extrai o email do JWE e consulta o papel no
  PostgreSQL. O `RequestContext` do grafo propaga `email`, mas não possui ainda
  cargo e loja autorizada como contexto estruturado.
- `Evidence` aceita hoje somente `metric` e `faq_document` como
  `source_type`. O juiz recebe evidências tipadas e não deve aprovar uma
  resposta sem evidência suficiente.
- Nenhum requisito atual autoriza o chatbot ou um agente remoto a executar
  pedido, promoção, escrita comercial ou alteração de registros.

### Propostas técnicas, ainda não aprovadas

- Usar A2A como um adapter de integração, sem criar um sexto agente local nem
  permitir comunicação direta entre executores locais fora do `GraphState`.
- Publicar o Quistock como uma fachada A2A com skills controladas. “Expor todo
  o sistema” significa disponibilizar as capacidades autorizadas do serviço,
  e não liberar SQL, tools internas, prompts, guardrails ou banco diretamente.
- Publicar inicialmente apenas as skills `faq` e `product_flow`; router,
  compiler, judge e guardrails permanecem detalhes internos da fachada.
- Começar a integração consumida com um peer conhecido e uma capacidade
  somente leitura. Streaming, push notifications, registry de peers e tarefas
  longas ficariam fora do MVP acadêmico.
- Adotar A2A 1.0.0 com uma única interface REST/JSON e publicar o card em
  `/.well-known/agent-card.json`; em desenvolvimento, permitir URL explícita
  configurada por ambiente para o mock local.
- Usar bearer próprio do ambiente no mock. A credencial não será publicada no
  AgentCard nem versionada; a evolução para token assinado curto fica prevista
  para um ambiente compartilhado ou produção.
- Tratar toda resposta remota como não confiável até validação de schema,
  autorização, proveniência e evidências. Texto remoto sem evidência não deve
  chegar ao juiz como fato aprovado.

## Decisões que o clarify precisa fechar

| ID | Decisão | Estado | Recomendação inicial | Impacto |
|---|---|---|---|---|
| A2A-DEC-001 | Papel do Quistock | confirmado | Cliente e servidor A2A, com fachada própria e consumo de outro sistema | Define rotas, cards e testes nos dois sentidos |
| A2A-DEC-002 | Escopo exposto | confirmado no objetivo; catálogo aberto | Expor o sistema como fachada com skills autorizadas; não expor executores, banco ou tools diretamente | Define catálogo, router e superfície de segurança |
| A2A-DEC-003 | Peer de referência | confirmado no caminho; identidade aberta | Integração externa existente como alvo; mock local como primeiro peer | Define ambiente e evidências da primeira implementação |
| A2A-DEC-004 | Versão e binding | confirmado | A2A 1.0.0, REST/JSON, `SendMessage` síncrono; sem streaming/push no MVP | Define SDK, schema e timeout |
| A2A-DEC-005 | Descoberta e card | confirmado | Card público mínimo em `/.well-known/agent-card.json`; assinatura não bloqueia o mock | Define publicação, cache e segurança do card |
| A2A-DEC-006 | Autenticação serviço a serviço | decisão a detalhar | Cliente confiável cadastrado localmente no mock; não aceitar chamadas anônimas; evolução para token curto assinado | Define registro do peer, segredo/configuração e escopos |
| A2A-DEC-007 | Contexto autorizado | aberto | Propagar email, cargo, loja e correlação em contexto assinado/delegado; nunca aceitar alteração pelo modelo | Depende da confiança entre os serviços |
| A2A-DEC-008 | Evidência remota | confirmado na regra; schema aberto | Aceitar somente fonte original verificável, com envelope estruturado e proveniência | Exige extensão de `Evidence` e do juiz |
| A2A-DEC-009 | Falha e retry | proposto/aceito para detalhamento | Falha fechada e um retry transitório com o mesmo identificador | Define latência, idempotência, fallback e SLO |
| A2A-DEC-010 | Demonstração acadêmica | confirmado | Mock peer com card, sucesso grounded e timeout/401; capturar correlação, evidência e decisão do juiz | Define evidências navegáveis da entrega |

## Contrato-alvo em discussão

### Descoberta e publicação

O servidor A2A deve publicar um `AgentCard` que descreva identidade,
capacidade, skill, interface, versão e requisitos de autenticação. O card não
deve conter tokens, emails de usuários, prompts privados, segredos ou detalhes
internos desnecessários. Se o card for protegido ou tiver conteúdo sensível,
deve existir uma decisão específica sobre card público, card estendido e
assinatura.

Para um cliente A2A, a descoberta deve produzir um peer validado por:

- URL permitida por ambiente, sem aceitar URL arbitrária produzida pelo modelo;
- versão de protocolo e binding suportados;
- skill compatível com a intenção roteada;
- esquema de autenticação esperado;
- identidade do servidor validada por TLS e, se decidido, assinatura do card.

### Identidade, autenticação e escopo

O usuário entra pelo JWE já validado pela API. O router ou modelo não pode
escolher email, cargo ou loja. O serviço deve derivar o contexto autorizado de
fontes confiáveis antes da chamada A2A e impedir que campos equivalentes no
texto, body ou metadata do cliente ampliem acesso.

O contrato precisa responder se o peer recebe:

1. email bruto, email como `sub` ou um identificador pseudônimo;
2. cargo funcional ou apenas scopes derivados;
3. uma loja, várias lojas ou nenhum escopo;
4. o contexto no token de serviço, em headers autenticados, no payload A2A ou
   em combinação desses mecanismos.

Mesmo que o peer receba contexto autorizado, ele não pode ser tratado como
autoridade para ampliar o escopo. A resposta deve carregar a correlação do
pedido, mas não deve persistir credenciais, PII desnecessária ou raciocínio
interno.

### Resultado remoto e evidências para o juiz

O adapter A2A deve validar uma resposta estruturada antes de atualizar o
`GraphState`. O resultado mínimo em discussão é:

```json
{
  "schema_version": "1.0",
  "status": "success",
  "task_id": "server-assigned-task-id",
  "agent": "remote_product_insights",
  "agent_card_version": "1.0.0",
  "answer": "texto consultivo opcional",
  "data": {},
  "evidence": [
    {
      "evidence_id": "a2a-task-id-source-1",
      "source_type": "a2a_agent",
      "source_id": "metric-publication-2026-09-30",
      "content": "referência ou dado verificável",
      "metadata": {
        "task_id": "server-assigned-task-id",
        "trace_id": "trace-id",
        "freshness": "2026-09-30T00:00:00Z"
      }
    }
  ],
  "warnings": []
}
```

Esse JSON é somente um formato de discussão; não é contrato aprovado. O
juiz deve considerar a resposta remota não confiável até verificar:

- schema e campos obrigatórios;
- correspondência entre `task_id`, `request_id` e `trace_id`;
- identidade do peer e versão do card;
- autorização e loja da evidência;
- frescor e proveniência da fonte original;
- citações existentes no conjunto de evidências recebido.

O conjunto mínimo de evidência em discussão é:

- `evidence_id` estável;
- `source_id` da fonte original;
- `source_type`;
- `source_uri` ou referência permitida ao repositório original;
- versão ou data de publicação da fonte;
- data de observação/frescor;
- conteúdo ou dado verificável;
- `task_id` e `trace_id` da chamada que trouxe a evidência.

Uma declaração do peer sem esses dados não será considerada evidência apenas
por ter vindo de uma conexão A2A.

Sem evidência verificável, o resultado deve ser `partial`, `unavailable` ou
`insufficient_evidence`, conforme o contrato final, e nunca uma afirmação
aprovada pelo juiz por fallback textual.

### Falhas, segurança e limites

O contrato deverá definir pelo menos:

- timeout de conexão e timeout total;
- limite de tamanho do card, mensagem e resposta;
- retry limitado, idempotência por `message_id` e ausência de retry para
  operações não idempotentes;
- mapeamento de `401`, `403`, schema inválido, rate limit, timeout, erro 5xx e
  peer indisponível;
- fallback controlado que não invente resposta;
- TLS, allowlist de peer, rotação de credencial e proteção contra SSRF;
- redaction de email, token, prompt privado, conteúdo sensível e payload bruto
  em logs comuns;
- isolamento de instruções contidas no conteúdo remoto para que não alterem a
  política do agente local.

## Perguntas restantes da primeira rodada

As respostas anteriores fecharam a direção geral. Restam estas escolhas para
transformar o clarify em uma spec implementável:

1. Para o mock, confirmamos um AgentCard público mínimo em
   `/.well-known/agent-card.json`, sem assinatura digital obrigatória?

2. Confirmamos que o mock terá um cliente cadastrado localmente e um segredo
   compartilhado de ambiente para provar a origem da chamada? “Cadastrar o
   cliente dentro do Quistock” será autorização/configuração, não autenticação
   isolada.

3. Confirmamos que o contexto autorizado será um contexto assinado/delegado
   pelo sistema chamador, contendo `email`, `role`, `store_id`, `scopes`,
   `request_id`, `trace_id`, `aud` e `exp`, sem o modelo poder alterar esses
   valores? Para o mock, podemos usar uma chave compartilhada de ambiente.

4. Confirmamos as skills públicas iniciais `faq` e `product_flow`, com
   `product_flow` mapeada internamente para `product_workflow`? `router`,
   `compiler`, `judge` e guardrails permanecem internos.

5. Quando a integração sair do mock, qual será o nome ou domínio do peer
   externo real? Até lá, usamos `mock_external_agent` controlado pelos testes.

6. Para considerar uma fonte original verificável, confirmamos exigir
   `evidence_id`, `source_id`, `source_type`, `source_uri` ou referência
   permitida, versão/data, frescor, conteúdo verificável, `task_id` e
   `trace_id`? Uma análise remota sem esses dados será descartada pelo juiz.

7. Confirmamos os dois cenários acadêmicos mínimos: sucesso com juiz
   aprovando evidências remotas e falha por timeout ou `401` sem resposta
   inventada, usando no máximo um retry transitório com o mesmo identificador?

## Critérios de aceite a confirmar após as respostas

- **CA-A2A-001**: o papel do Quistock, peer, skill e direção da chamada estão
  registrados sem ambiguidade.
- **CA-A2A-002**: existe um AgentCard versionado, publicável e validável, sem
  segredos ou PII desnecessária.
- **CA-A2A-003**: email, cargo, loja, `request_id` e `trace_id` têm origem,
  formato, audience, expiração e regra de não-elevação de privilégio definidos.
- **CA-A2A-004**: resposta, erro, retry, timeout, idempotência e fallback têm
  schemas e códigos observáveis.
- **CA-A2A-005**: resultado remoto só pode contribuir para a resposta final
  como evidência validada pelo juiz; conteúdo não fundamentado é bloqueado.
- **CA-A2A-006**: testes cobrem descoberta, autenticação, isolamento de loja,
  schema inválido, indisponibilidade, timeout, retry e correlação.
- **CA-A2A-007**: a demonstração acadêmica produz evidências navegáveis de
  sucesso e de falha segura.

## Fora do escopo desta etapa

- implementação de rota, SDK ou worker A2A;
- escolha definitiva de credenciais e secrets;
- autorização comercial além da consulta necessária ao caso demonstrado;
- escrita em PostgreSQL, MongoDB, Redis ou Qdrant pelo peer;
- streaming, push notifications, registry de agentes e descoberta dinâmica;
- abertura de tasks executáveis antes do fechamento das perguntas que mudam a
  arquitetura.

## Referências

- [A2A Protocol Specification 1.0.0](https://a2a-protocol.org/v1.0.0/specification/)
- [A2A Agent Discovery](https://a2a-protocol.org/dev/topics/agent-discovery/)
- `AGENTS.md`, seção “Fontes de verdade e estado atual”
- `src/agents/schemas/agent_card.py`
- `src/agents/registry.py`
- `src/graphs/state.py`
- `src/graphs/adapters.py`
- `docs/sdd/academic-constraints.md` no repositório Quistock
- `docs/planejamento-multiagente-fastapi.md` no repositório Quistock
