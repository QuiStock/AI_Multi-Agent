# Plano de desenvolvimento A2A do Quistock

**Status:** proposta consolidada para revisão do usuário  
**Escopo:** fachada A2A de entrada, cliente A2A de saída e adaptação do fluxo multiagente.  
**Código alterado por este documento:** nenhum. Este arquivo registra o plano; a implementação começa depois da revisão.

> Este plano consolida as decisões da conversa e fecha escolhas técnicas para que a revisão seja concreta. Onde aparece “decisão proposta”, trata-se de uma escolha explícita deste plano para aprovação, não de algo já implementado.

## 1. Resultado esperado

O Quistock terá dois papéis:

1. **Servidor A2A:** outro sistema poderá descobrir as capacidades do Quistock e enviar uma mensagem para o mesmo fluxo de conversa usado pela API atual.
2. **Cliente A2A:** o roteador poderá encaminhar uma pergunta a um sistema externo autorizado e incorporar a resposta ao fluxo do Quistock.

O Quistock continuará responsável por autenticação do sistema chamador, escopo de loja, permissões locais, memória, tom de voz, guardrails e rastreamento. Cada sistema externo será responsável por autenticar seus próprios usuários e afirmar corretamente a identidade externa, a loja e o cargo daquela chamada.

O sistema de caminhões **não será criado neste trabalho**. No desenvolvimento, a chamada de caminhões usa um mock local claramente identificado. Em produção, o cliente aponta para o serviço definitivo se ele oferecer um contrato A2A compatível.

## 2. Decisões reunidas

### Confirmadas na conversa

- O Quistock será cliente e servidor A2A.
- A entrada A2A será uma fachada para o serviço de conversa atual; não haverá um endpoint público por agente interno.
- Chamadas A2A passam pelos guardrails de entrada e saída e pelo mesmo grafo da conversa normal.
- O sistema chamador autentica o usuário externo. O Quistock não exige JWT humano Quistock e não procura nem cria esse usuário em `user_account` ou `user_store`.
- A chamada de entrada contém `store_id`, ID estável do usuário externo e cargo. O `store_id` recebido já é o ID da loja no Quistock; não haverá tabela de correspondência entre IDs de lojas.
- O Quistock autentica o sistema cliente, confirma por `SELECT` que a loja existe e está ativa e que o cargo existe. O cliente externo é a autoridade que confirma a associação da pessoa à loja e o cargo que envia.
- Os cargos A2A aceitos para esse fluxo são gerente (`MANAGER`) e funcionário (`EMPLOYEE`). O Quistock aplica as permissões locais correspondentes; não aceita cargo regional neste escopo.
- O Product Workflow via A2A é somente leitura e deve filtrar cada consulta pela loja autorizada e pela visibilidade do cargo.
- A resposta do peer A2A é uma declaração atribuída ao peer. Ela não é prova independente da verdade dos fatos.
- O compilador local permanece no fluxo para aplicar o tom de voz e as regras de conversa do Quistock, sem acrescentar fatos nem alterar o sentido da resposta externa.
- Para resposta A2A, o juiz verifica consistência entre a resposta original do peer e o rascunho compilado. Não exige uma segunda validação factual independente.
- Haverá um mock local do sistema externo de caminhões; nenhum novo serviço de caminhões será desenvolvido nesta etapa.
- A seleção dinâmica entre vários peers fica como extra posterior. O MVP usa um peer e uma skill externos fixos e autorizados.

### Decisões técnicas propostas neste plano

- Protocolo A2A 1.0, binding HTTP+JSON, mensagem síncrona e somente partes de texto no MVP.
- O AgentCard do Quistock será público em `GET /.well-known/agent-card.json`; ele não conterá segredos, prompts ou configuração privada.
- A mensagem de entrada será recebida em `POST /a2a/message:send`, protegida por credencial de serviço. O endpoint devolverá diretamente `SendMessageResponse` com uma `Message` de agente.
- Não serão usados `Task`, `TaskUpdater`, `EventQueue`, streaming, push notification ou Redis para responder a esse fluxo síncrono.
- A credencial identifica o sistema cliente. A loja e o cargo são afirmações desse cliente confiável, verificadas contra a loja e o catálogo de cargos do Quistock. Não haverá vínculo fixo entre um token único e uma loja no MVP.
- A identidade interna de conversa será pseudonimizada por HMAC com `client_id`, loja, ID externo, cargo e `contextId`. O ID externo bruto não será registrado em logs comuns.
- O roteador inicial só pode selecionar `truck_info_agent/truck_specs`; nunca escolhe URL, token ou cabeçalho.
- Resposta A2A válida, mas indisponibilidade de peer, será convertida em resposta controlada da conversa. Não haverá fallback silencioso para FAQ nem fabricação de resposta.
- O timeout remoto permanece em 8 segundos por chamada HTTP, conforme configuração existente. Para a consulta externa, será permitido no máximo um retry de leitura em timeout ou erro transitório 5xx, usando o mesmo `messageId`; erros 4xx e resposta inválida não serão repetidos.

## 3. Termos do protocolo neste plano

| Termo | Significado simples no Quistock |
|---|---|
| **A2A** | Protocolo para um agente/sistema descobrir e chamar outro agente/sistema. Não autentica automaticamente o usuário final nem garante a verdade da resposta. |
| **AgentCard** | Cartão JSON público que informa nome, versão, endpoint, transporte e skills oferecidas pelo sistema. Não contém credenciais. |
| **Skill** | Capacidade de negócio anunciada no AgentCard, como `faq`, `product_flow` ou `truck_information`. Não é um executor interno exposto diretamente. |
| **Peer** | Sistema A2A remoto cadastrado e autorizado pelo Quistock. No MVP de saída, `truck_info_agent`. |
| **Message** | Mensagem de uma única interação. O usuário envia uma `Message`; o peer responde com uma `Message`. |
| **Part** | Conteúdo de uma mensagem. O MVP aceita somente partes de texto. |
| **messageId** | Identificador da mensagem; permite correlacionar e deduplicar uma chamada. |
| **contextId** | Identificador do contexto/conversa no protocolo. O Quistock o associa a uma conversa isolada por cliente, loja, usuário externo e cargo. |
| **Task** | Unidade A2A para trabalho que pode continuar além da resposta imediata. Não será usada no MVP síncrono. |
| **Artifact** | Resultado produzido durante uma Task. Não será necessário no MVP, que retorna uma Message textual. |
| **EventQueue / TaskUpdater** | Mecanismos do SDK para publicar eventos e atualizar Tasks. Não são uma fila obrigatória para cada requisição HTTP; não serão usados neste fluxo síncrono. |
| **Evidência `a2a_agent`** | Registro interno de qual peer respondeu e qual mensagem foi recebida. Comprova a origem da declaração, não a veracidade independente do conteúdo. |

## 4. Fluxo-alvo

### Quistock como servidor

```text
Sistema externo autentica a pessoa
  → envia Message A2A + credencial de serviço + store_id + external_user_id + role
  → Quistock autentica o sistema chamador
  → Quistock valida loja ativa e cargo aceito com SELECT
  → Quistock cria identidade interna pseudonimizada e isola contextId
  → ConversationService chama o fluxo normal
  → guardrail de entrada → contexto/memória → roteador → agente escolhido
  → compilador → juiz → guardrail de saída → persistência
  → Quistock retorna SendMessageResponse com Message do agente
```

### Quistock como cliente

```text
Mensagem recebida pela conversa
  → guardrail de entrada → contexto/memória → roteador escolhe external_a2a
  → adaptador valida peer e skill permitidos
  → mock local ou cliente HTTP A2A chama truck_info_agent/truck_specs
  → resposta do peer entra em agent_results.external_a2a e em evidences
  → compilador adapta tom/forma do Quistock preservando conteúdo e atribuição
  → ramo A2A do juiz compara rascunho com resposta original do peer
  → guardrail de saída → persistência → resposta ao usuário
```

Se o peer estiver indisponível ou responder fora do contrato, o grafo retorna a mensagem controlada de indisponibilidade. Essa falha não vira resposta factual do FAQ.

## 5. Contrato de entrada A2A

### Descoberta do serviço

`GET /.well-known/agent-card.json` será público e descreverá apenas capacidades externas disponíveis. No MVP, o card poderá anunciar:

- `faq`: consulta de conteúdo documental autorizado;
- `product_flow`: consulta de sugestões conforme cargo e loja;
- `truck_information`: consulta encaminhada ao peer externo configurado, com indicação de simulação enquanto estiver em mock.

A resposta do card não incluirá tokens, email, IDs de usuário, prompts, SQL, tools internas, dados de loja ou detalhes de guardrails.

### Envio de mensagem

`POST /a2a/message:send` aceitará A2A 1.0 sobre HTTP+JSON. O cliente enviará:

```http
Authorization: Bearer <credencial-do-sistema-cliente>
A2A-Version: 1.0
X-Quistock-Store-Id: 42
X-External-User-Id: usuario-externo-123
X-External-Role: EMPLOYEE
Content-Type: application/a2a+json
Accept: application/a2a+json
```

Exemplo simplificado do corpo:

```json
{
  "message": {
    "messageId": "msg-789",
    "contextId": "conv-456",
    "role": "ROLE_USER",
    "parts": [
      { "text": "Quais sugestões de promoção estão aguardando triagem?" }
    ]
  }
}
```

Regras de entrada:

- `messageId` é obrigatório, estável durante retry e limitado a 128 caracteres.
- `contextId` pode ser omitido no primeiro turno; se omitido, o Quistock cria um e o devolve. Nos turnos seguintes, o cliente reutiliza o `contextId` retornado.
- O remetente deve ser `ROLE_USER`; a mensagem deve conter ao menos uma parte textual e ter no máximo 4.000 caracteres.
- Partes de arquivo, URL, áudio, imagem, mensagens de agente e Tasks são rejeitadas no MVP.
- `store_id` deve ser um inteiro positivo que exista em `store` e esteja `ACTIVE` no PostgreSQL do Quistock.
- `role` deve existir em `role.code` e ser `MANAGER` ou `EMPLOYEE`. `REGIONAL_MANAGER` e qualquer outro cargo são recusados.
- `external_user_id` deve ser estável dentro do sistema externo e satisfazer o limite de tamanho/formato do contrato. Ele não precisa existir no Quistock.
- O corpo, a mensagem natural e a saída do roteador nunca podem trocar os headers autenticados nem ampliar `store_id` ou `role`.

### Resposta

A resposta imediata será um envelope A2A com mensagem de `ROLE_AGENT`, `messageId` novo e o `contextId` recebido/criado. A resposta textual será `final_response` do serviço de conversa. Erros de autenticação e envelope inválido usam erro HTTP; falhas de agente ou peer depois da aceitação da mensagem viram respostas conversacionais controladas e ficam identificadas no status/trace interno.

## 6. Autenticação e autorização de usuário externo

O fluxo não é um bypass de autenticação. São duas responsabilidades diferentes:

1. **Autenticação do sistema:** o bearer token identifica um cliente A2A previamente configurado no Quistock. A chamada é servidor-a-servidor e usa HTTPS fora do ambiente local. O token fica em configuração secreta, nunca no AgentCard nem no prompt.
2. **Autenticação da pessoa:** o sistema externo autentica a pessoa e afirma `external_user_id`, `store_id` e `role`. O Quistock confia nessa afirmação porque ela veio de um cliente A2A autenticado e autorizado a atuar como provedor de identidade para essa integração.

No Quistock, antes do grafo:

- executar `SELECT` parametrizado para confirmar que a loja recebida existe e está ativa;
- executar `SELECT` parametrizado em `role` para resolver `MANAGER` ou `EMPLOYEE` ao `role_id` local;
- rejeitar loja ou cargo inexistente/inativo/não permitido;
- não consultar `user_account` ou `user_store` para a pessoa externa;
- não criar usuário, associação, loja, role ou permissão;
- propagar ao grafo apenas o principal pseudonimizado, `role_id` local, `store_id`, `client_id` e correlação necessária.

O cliente externo deve manter o bearer no backend dele, nunca em aplicativo público/browser. Ele deve validar que aquela pessoa pertence à loja enviada e possui o cargo enviado. O Quistock valida a existência e os limites locais, mas não tem como revalidar uma identidade que deliberadamente não existe no seu cadastro.

### Isolamento da conversa

- `conversation_id` é derivado por HMAC de `client_id`, `store_id`, ID externo, cargo e `contextId`.
- `request_id` é derivado de `client_id`, `store_id`, ID externo, cargo, `contextId` e `messageId`.
- Reutilizar o mesmo `contextId` por outra pessoa, loja, cliente ou cargo não dá acesso à conversa anterior.
- A mudança de cargo gera um contexto interno diferente e não reutiliza histórico produzido sob outro nível de permissão.
- O histórico é salvo pelo mecanismo de conversa existente. Não haverá uma memória paralela só para A2A.

### Permissões do Product Workflow via A2A

| Cargo afirmado pelo cliente | Consulta permitida | Visibilidade aplicada no servidor |
|---|---|---|
| `EMPLOYEE` | Buscar/detalhar sugestões disponíveis para triagem do funcionário | Somente itens elegíveis em `IN_EMPLOYEE_TRIAGE` e `available_for_triage = TRUE`, sempre na loja recebida. |
| `MANAGER` | Buscar/detalhar sugestões encaminhadas ao gerente | Somente itens `SENT_TO_MANAGER`, sempre na loja recebida. |

O repositório usa consultas parametrizadas e o `store_id` autorizado como filtro obrigatório. O caminho A2A não depende de joins com `user_account`/`user_store`. O fluxo normal continua com sua autenticação e seus filtros atuais por usuário/loja. Nenhuma rota A2A escreve sugestão, decisão, pedido ou promoção.

## 7. Quistock como cliente A2A

### Rota do roteador

O MVP acrescenta a rota genérica `external_a2a` ao catálogo de rotas. Na primeira entrega, ela pode escolher apenas:

```text
peer_id = truck_info_agent
skill_id = truck_specs
```

A decisão estruturada do roteador carrega IDs, nunca URL, bearer, header ou parâmetros de autorização. O servidor valida novamente peer e skill antes da chamada. O grafo continua com um nó genérico `external_a2a`; não cria um agente local novo por peer.

### Mock e peer definitivo

- Em desenvolvimento, `A2A_TRUCK_MODE=mock` devolve uma resposta simulada no processo atual. Ela deve informar que é simulada e que não há dado técnico verificado. O mock testa roteamento, contrato, compiler e juiz; não serve como fonte real sobre caminhões.
- Em produção, `mock` é recusado. O adaptador usa `A2A_TRUCK_CARD_URL`, `A2A_TRUCK_ENDPOINT_URL` e `A2A_TRUCK_SERVICE_TOKEN` protegidos por configuração de ambiente.
- O cliente valida a interface HTTP+JSON A2A 1.0, endpoint configurado e existência da skill `truck_specs` no AgentCard. Não segue redirects e exige HTTPS em produção.
- A pergunta enviada é somente a necessária para a consulta e a correlação A2A. Não envia JWT humano Quistock, email, role, loja, histórico completo, prompts ou dados comerciais. O catálogo de caminhões é tratado como consulta pública no escopo atual.
- Substituir o mock por configuração só basta se o serviço definitivo implementar esse contrato A2A. Se usar outro protocolo, será necessário um adapter de tradução; isso não altera o serviço de caminhões que está fora deste projeto.

### Resposta e evidência do peer

O resultado remoto é salvo em `GraphState.agent_results.external_a2a`. O adapter preserva a mensagem original recebida e cria uma evidência interna com, no mínimo:

```json
{
  "evidence_id": "a2a:truck_info_agent:message-123",
  "source_type": "a2a_agent",
  "source_id": "message-123",
  "content": "resposta textual original do peer",
  "metadata": {
    "peer_id": "truck_info_agent",
    "skill_id": "truck_specs",
    "trust_level": "peer_assertion",
    "mock": false
  }
}
```

Essa evidência registra a origem e a resposta do peer. Ela não afirma que o Quistock conferiu o catálogo ou uma fonte técnica original.

## 8. Compiler, Judge e guardrails

### Compiler local

O sistema externo pode ter seu próprio router, agentes, compilador e juiz. O Quistock recebe a resposta final que o peer produziu e usa o compiler local apenas para adequá-la à experiência Quistock:

- tom de voz, idioma, clareza, concisão e formatação locais;
- atribuição clara ao peer, por exemplo “Segundo o sistema de caminhões…”;
- indicação explícita de simulação quando a origem for o mock;
- preservação de ressalvas, incerteza, números, nomes e limites da resposta original.

O compiler não adiciona fatos, números, fontes, conclusões ou recomendações que não estejam na resposta do peer. Se não houver adaptação necessária, ele pode devolver o conteúdo praticamente sem alteração.

### Ramo A2A do Judge

O juiz mantém os dois comportamentos:

- **Rotas internas (`faq`, `product_workflow`):** comportamento atual de validação de citações e suporte nas evidências locais.
- **Rota `external_a2a`:** validação específica da resposta externa. Primeiro confere de forma determinística que existe resultado A2A bem-sucedido, que a evidência citada pertence ao peer/skill selecionado, que as citações existem e que o mock está marcado. Depois compara semanticamente o rascunho do compiler com a resposta original do peer para verificar que o rascunho não contradiz, omite ressalvas relevantes nem acrescenta alegações factuais.

Se a resposta compilada for fiel, o juiz aprova e o fluxo continua. Se o resultado A2A estiver ausente, as referências não baterem ou o rascunho trouxer fatos sem suporte na resposta do peer, o juiz bloqueia e o usuário recebe uma mensagem controlada. O juiz não pesquisa, consulta catálogo, fonte externa ou banco para provar a veracidade da afirmação do peer.

### Output guardrail

O guardrail local continua verificando segurança, privacidade, tamanho e formato da resposta. Para a rota externa, ele não deve exigir uma fonte independente que o contrato A2A não fornece. O seu papel permanece distinto do juiz: impedir saída local proibida/insegura; o juiz confere fidelidade ao peer.

## 9. Memória, filas, repetição e rastreamento

- `contextId` agrupa os turnos A2A de uma conversa; ele não autentica nem concede acesso.
- A conversa continua usando `ConversationService`, persistência MongoDB e checkpointer já existentes.
- `messageId` identifica uma chamada. A mesma combinação de identidade/contexto/messageId e conteúdo retorna a resposta salva. O mesmo ID com conteúdo diferente retorna HTTP 409. Uma chamada concorrente ainda em processamento retorna HTTP 409 com `Retry-After`.
- A reserva de idempotência e a resposta ficam na coleção MongoDB configurada para respostas A2A; Redis não será introduzido para esse caso.
- `request_id`, `trace_id`, `peer_id`, `skill_id`, rota e status são correlacionados. Tokens e o `external_user_id` bruto não entram em logs comuns.
- `EventQueue` não é uma fila de execução que precisa ficar rodando entre requisições. No modo síncrono, o servidor HTTP recebe a requisição, executa o grafo e devolve a resposta. `EventQueue`/`TaskUpdater` só serão necessários se uma entrega futura adotar Tasks, streaming ou notificações.

## 10. Falhas e respostas controladas

| Condição | Comportamento |
|---|---|
| Token ausente/inválido | HTTP 401; não inicia o grafo. |
| Cliente sem credencial configurada | HTTP 503 de configuração; não inicia o grafo. |
| `store_id` inexistente/inativo | HTTP 403; não inicia o grafo. |
| Role inexistente ou diferente de `MANAGER`/`EMPLOYEE` | HTTP 403; não inicia o grafo. |
| Envelope, `messageId`, `contextId`, parte ou tamanho inválido | HTTP 422; não inicia o grafo. |
| `messageId` reutilizado com conteúdo diferente ou requisição simultânea | HTTP 409; não cria segundo turno. |
| Peer remoto 401/403, card incompatível, schema inválido ou skill ausente | Falha controlada da rota externa; sem retry para 4xx/contrato inválido e sem fallback para outra skill. |
| Timeout ou 5xx transitório do peer de leitura | Um retry com os mesmos IDs; depois, resposta controlada de indisponibilidade. |
| Mock selecionado em produção | Erro de configuração; nenhuma resposta simulada é apresentada como dado real. |
| Judge A2A não consegue confirmar fidelidade | Bloqueia o rascunho e retorna resposta controlada. |
| Store/role/PostgreSQL indisponível | HTTP 503 antes do grafo; não prossegue com escopo presumido. |

A implementação sanitiza detalhes técnicos retornados ao usuário. O trace mantém código de erro estável e diagnóstico sem token, PII ou payload bruto desnecessário.

## 11. Etapas de desenvolvimento

### Etapa 0 — Consolidar a especificação após aprovação deste plano

- Atualizar `specs/004-a2a-clarify/spec.md` e `implementation.md` para refletir o contrato de papel externo, store validado diretamente, peer assertion e ramo A2A do juiz.
- Revisar o ADR de fachada para remover a exigência antiga de fonte original verificável para aprovar resposta de peer.
- Registrar requisitos funcionais, não funcionais e critérios de aceite abaixo.

**Saída:** documentação de contrato consistente, antes de novas alterações de código.

### Etapa 1 — Contratos, settings e principal A2A

- Definir schemas para principal A2A, cabeçalhos, contexto externo, resultado remoto e evidência `a2a_agent`.
- Validar `A2A-Version`, `messageId`, `contextId`, texto e tamanho.
- Manter bearer secreto em ambiente e comparação segura.
- Implementar `SELECT` somente leitura para loja ativa e resolução do role code; rejeitar cargo fora da allowlist.
- Criar identidade interna HMAC por cliente/loja/usuário/cargo/contexto.

**Saída:** fronteira de confiança e identidade testáveis isoladamente.

### Etapa 2 — Fachada A2A de entrada

- Expor o AgentCard público atualizado.
- Proteger `POST /a2a/message:send` com principal A2A.
- Traduzir a `Message` para `ConversationRequest` e chamar `ConversationController`/`ConversationService` atual.
- Retornar `SendMessageResponse` e `contextId`.
- Preservar isolamento e idempotência no MongoDB.

**Saída:** cliente A2A consegue usar as capacidades autorizadas do grafo Quistock.

### Etapa 3 — Product Workflow para gerente e funcionário externos

- Expandir o caminho `a2a_store_id` para os dois cargos suportados.
- Aplicar filtro direto por loja em busca e detalhe, com status/visibilidade por role.
- Não depender de `user_account` nem `user_store` no caminho A2A.
- Preservar sem alterações o caminho convencional autenticado por usuário local.
- Manter agente, tools, SQL e acesso comercial em modo somente leitura.

**Saída:** funcionário externo consulta apenas a fila de triagem e gerente externo apenas a fila gerencial da loja enviada.

### Etapa 4 — Cliente A2A e peer de caminhões

- Manter a interface do mock e a interface remota atrás de um único executor.
- Validar AgentCard, interface, protocolo, endpoint configurado e skill.
- Enviar `SendMessage` com `messageId`/`contextId` correlacionados e bearer próprio do Quistock.
- Validar a resposta síncrona `Message` e registrar o peer assertion.
- Recusar mock em produção; configurar HTTPS e timeout remoto.

**Saída:** rota de caminhões demonstrável em mock e pronta para apontar a um peer A2A compatível.

### Etapa 5 — Roteador, grafo, compiler e juiz

- Ativar a rota `external_a2a` no roteador e no mapa de rotas do grafo.
- Garantir que a saída estruturada do router só aceite `truck_info_agent/truck_specs` no MVP.
- Transportar `agent_results.external_a2a` e `Evidence` pelo estado compartilhado.
- Adaptar o compiler para preservar sentido/ressalvas, aplicar o tom Quistock, atribuir peer e marcar mock.
- Implementar o ramo A2A do judge: proveniência/IDs + fidelidade semântica; manter o ramo atual para rotas internas.
- Manter output guardrail e persistência após aprovação.
- Manter caminho controlado para indisponibilidade externa.

**Saída:** uma pergunta roteada ao peer atravessa o grafo inteiro e não ganha alegações novas.

### Etapa 6 — Segurança, isolamento e observabilidade

- Testar isolamento entre sistemas clientes, pessoas, cargos, contextos e lojas.
- Confirmar que falhas de auth/loja/role ocorrem antes do grafo.
- Conferir idempotência, retry limitado, mensagens concorrentes e indisponibilidade.
- Rastrear IDs A2A e status sem persistir segredo ou identidade externa em texto claro.
- Atualizar logs e métricas para contagem/latência/erro da rota `external_a2a`.

**Saída:** evidências de funcionamento seguro e diagnóstico operacional.

### Etapa 7 — Extra: catálogo dinâmico de peers

Executar depois do MVP de um peer:

- Manter registro administrativo/configurado de peers e skills permitidos.
- Obter e validar AgentCards apenas de URLs cadastradas e HTTPS em produção.
- Passar ao roteador somente nomes e descrições de skills já filtrados por autorização e classificação de dados.
- Validar novamente `peer_id`/`skill_id` no servidor e resolver URL/token pelo registro, nunca pela resposta do modelo.
- Limitar cada turno a uma chamada externa; impedir ciclos de encaminhamento.
- Adicionar peer novo por registro/configuração e testes, sem criar novo nó no LangGraph.

**Saída:** seleção entre peers autorizados; “dinâmico” não significa chamar qualquer URL arbitrária.

## 12. Arquivos previstos

O plano prevê alterar somente arquivos relacionados ao contrato A2A e aos pontos de integração existentes. Os nomes finais serão confirmados ao iniciar cada etapa.

| Área | Arquivos prováveis | Responsabilidade da mudança |
|---|---|---|
| A2A de entrada | `src/a2a_integration/inbound.py`, `src/api/dependencies.py`, `src/config.py` | Auth de serviço, validação de store/role, AgentCard, request/response e settings. |
| Conversa/identidade | `src/api/controllers/conversation_controller.py`, `src/api/services/conversation_service.py`, `src/graphs/state.py` | Propagar principal A2A e contexto de loja/cargo ao mesmo grafo sem mudar o endpoint normal. |
| Product Workflow | `src/agents/product_workflow/executor.py`, `repository.py`, `models.py`, `filters.py` | Consultas A2A com store explícito e leitura por cargo. |
| Cliente/saída A2A | `src/a2a_integration/external.py`, `src/agents/router/`, `src/graphs/contracts.py` | Peer fixo, mock/remote, validação de card, skill e contrato de resposta. |
| Grafo e estado | `src/graphs/adapters.py`, `decisions.py`, `agent_graph.py`, `state.py` | Roteamento, resultado A2A, evidência, compiler/judge e erro controlado. |
| Compiler/Judge | `src/agents/compiler/`, `src/agents/judge/`, guardrail de saída correspondente | Tom local e comparação de fidelidade para A2A; validação atual preservada para rotas internas. |
| Persistência/telemetria | `src/api/services/` e `src/observability/` já relacionados a turnos/traces | Repetição segura, correlação e status A2A. |
| Testes | `tests/test_a2a_facade.py`, novos testes do peer, grafo, judge e Product Workflow | Contratos, autorização, isolamento, sucesso, falha e fidelidade. |
| SDD | `specs/004-a2a-clarify/spec.md`, `implementation.md`, `adr-001-fachada-a2a.md` | Sincronizar as decisões depois da aprovação do plano. |

Não estão previstos arquivo de serviço de caminhões, migration comercial, novo usuário no PostgreSQL, novo agente local, nova rota de conversa paralela ou acesso de escrita ao banco comercial.

## 13. Requisitos e critérios de aceite

- **RF-A2A-001:** o Quistock publica AgentCard sem segredos e anuncia somente skills encaminhadas pelo grafo.
- **RF-A2A-002:** mensagem A2A autenticada passa pelo mesmo `ConversationService` e grafo das conversas convencionais.
- **RF-A2A-003:** a identidade externa não precisa existir em `user_account`; conversa é isolada por cliente, loja, pessoa, cargo e contexto.
- **RF-A2A-004:** loja recebida deve existir e estar ativa; role deve existir e ser `MANAGER` ou `EMPLOYEE`; o Quistock não cria nem altera esses dados.
- **RF-A2A-005:** Product Workflow aplica sempre escopo da loja e visibilidade do cargo no caminho A2A, em consultas e detalhes.
- **RF-A2A-006:** o router chama somente peer/skill cadastrados; no MVP, `truck_info_agent/truck_specs`.
- **RF-A2A-007:** resposta do peer vira `agent_results.external_a2a` e evidência `peer_assertion`, sem alegação de validação factual independente.
- **RF-A2A-008:** compiler preserva fatos e ressalvas do peer, aplica apresentação local e identifica mock.
- **RF-A2A-009:** ramo A2A do juiz aprova somente se a resposta compilada for fiel à mensagem original e à evidência A2A selecionada.
- **RF-A2A-010:** falha de peer produz resposta controlada; não há fallback que invente dados.
- **RNF-A2A-001:** nenhum JWT humano, bearer, prompt privado ou PII desnecessária é enviado ao peer de caminhões ou escrito em logs comuns.
- **RNF-A2A-002:** consultas comerciais são parametrizadas, read-only e isoladas por loja/cargo.
- **RNF-A2A-003:** IDs A2A são correlacionados e chamadas repetidas são idempotentes por `messageId` e conteúdo.
- **RNF-A2A-004:** o cliente remoto usa HTTPS em produção, timeout finito e no máximo um retry transitório de leitura.

Critérios observáveis:

1. Dado um usuário externo que não existe no PostgreSQL Quistock, quando o sistema cliente autenticado envia loja ativa e role permitido, então a mensagem percorre o grafo sem criar/consultar a conta local desse usuário.
2. Dada uma loja inexistente/inativa, role desconhecido ou cargo regional, quando chega uma chamada A2A, então ela é recusada antes do grafo.
3. Dado um funcionário A2A, quando consulta Product Workflow, então só recebe sugestões disponíveis para triagem na loja enviada.
4. Dado um gerente A2A, quando consulta Product Workflow, então só recebe sugestões encaminhadas ao gerente na loja enviada.
5. Dada uma resposta de peer válida, quando o compiler adapta o tom, então preserva sentido, dados e ressalvas; o juiz aprova apenas se o draft continuar fiel à mensagem original.
6. Dada uma resposta mock, quando ela chega ao usuário, então está marcada como simulação e não é apresentada como especificação técnica verificada.
7. Dado um draft que acrescenta um fato ausente da resposta A2A, quando passa pelo juiz, então é bloqueado.
8. Dado um peer sem resposta, com erro HTTP, card incompatível ou resposta inválida, então o usuário recebe a resposta controlada de indisponibilidade e o trace registra o erro sem credenciais.
9. Dada a repetição de `messageId` com mesmo conteúdo, então o sistema reaproveita a resposta; com conteúdo diferente, responde HTTP 409.
10. Dado um turno não A2A (FAQ ou Product Workflow), então o juiz mantém a regra atual de evidência local.

## 14. Fora do escopo do primeiro ciclo

- Implementar/operar o sistema de caminhões.
- Criar ou alterar usuário, loja, role ou associação comercial no PostgreSQL.
- Repassar JWT humano para outros sistemas.
- Expor executores, prompts, tools, SQL, memória ou guardrails como AgentCards independentes.
- Escrita de pedidos, promoções, sugestões ou decisões pelo fluxo A2A.
- Tasks longas, EventQueue, streaming, push notifications e execução assíncrona A2A.
- Seleção dinâmica de vários peers, que fica na Etapa 7.
- MCP. O cliente A2A chama agentes/sistemas remotos via A2A; MCP não é necessário para esse contrato.

## 15. Referências do projeto

- [Especificação A2A atual](spec.md)
- [Contrato executável A2A atual](implementation.md)
- [ADR da fachada A2A](adr-001-fachada-a2a.md)
- [Contexto SDD do Quistock](C:/Users/enzojoaquim-ieg/OneDrive%20-%20Instituto%20J%26F/Documentos/ChatGPT/Quistock/docs/sdd/project-context.md)
- [Conceitos do protocolo A2A](https://a2a-protocol.org/latest/topics/key-concepts/)
- [Especificação A2A 1.0.0](https://a2a-protocol.org/v1.0.0/specification/)

