# Plano de implementação A2A — Quistock servidor e cliente

> **Revisão de 2026-10-09:** o usuário autorizou a implementação com mock
> interno, sem criar o serviço de caminhões. A exigência de fonte original
> verificável foi substituída, neste ciclo, por atribuição explícita ao peer
> e identificação de resposta simulada. Consulte [implementation.md](implementation.md)
> para o contrato executável e as pendências. O texto abaixo é histórico.

**Estado:** proposto em 2026-10-09. O escopo confirmado pelo usuário é atuar
como servidor e cliente A2A e permitir ao router escolher uma capacidade
externa. O serviço de caminhões é o exemplo inicial proposto. A seleção entre
vários peers é um extra posterior. Este documento planeja a implementação;
nenhuma rota A2A está ativa no runtime atual.

## 1. Entenda as peças

| Termo | Significado neste projeto |
|---|---|
| Servidor A2A | Sistema que publica um AgentCard e recebe mensagens A2A. O Quistock e o sistema de caminhões serão servidores. |
| Cliente A2A | Sistema que lê o card de outro servidor e lhe envia mensagens. O Quistock será cliente do sistema de caminhões. |
| AgentCard | JSON de descoberta com endereço, protocolo, autenticação e skills anunciadas; não concede autorização. |
| Skill | Capacidade descrita no card, por exemplo `faq`, `product_flow` ou `truck_specs`. Não é necessariamente um agente interno. |
| Message | Entrada ou resposta textual/estruturada. Para o MVP, uma chamada `SendMessage` pode terminar com uma resposta direta. |
| Task | Identificador e estado de um trabalho acompanhado pelo protocolo. O MVP não precisa criar tarefas longas. |
| `contextId` | Identificador A2A para agrupar mensagens de uma conversa; não é memória nem prova de propriedade. |
| Registro de peers | Lista controlada dos sistemas externos permitidos, suas skills, credenciais e políticas. |
| Evidência | Fonte original verificável que sustenta um fato e pode ser avaliada pelo juiz local. |

O `EventQueue` do SDK, quando usado, entrega eventos do executor à camada A2A.
Na interação síncrona simples, o executor pode emitir uma única `Message` final.
Isso não cria uma fila Redis nem substitui a memória do LangGraph/MongoDB.

## 2. Estado atual e objetivo

O fluxo executável hoje é `HTTP -> input_guardrail -> context_enrichment ->
normalize_user_message -> router -> faq | product_workflow -> compiler ->
judge -> output_guardrail -> persist_turn`. Ambas as capacidades de domínio
estão registradas em `src/api/dependencies.py`; A2A ainda não está.

```text
App Quistock ── HTTP normal ──────────────────────────┐
                                                     ├─ serviço de conversa → mesmo grafo
Cliente A2A ── A2A → autenticação → adaptador ────────┘                         │
                                                                               │
                                                router → faq/product_workflow ─┤
                                                       → external_a2a ────────┤
                                                             │                 │
                                          cliente A2A Quistock │                 │
                                                             ↓                 ↓
                                           servidor de caminhões       compiler → judge
```

“Expor o sistema inteiro” significa publicar as **capacidades autorizadas**
do assistente por uma fachada. Router, prompts, tools, SQL, guardrails,
compilador, juiz, memória e observabilidade continuam internos. A rota A2A
usa o mesmo serviço de conversa, identidade, grafo e regras das rotas normais.

## 3. Escopo do primeiro ciclo

**Confirmado:** Quistock servidor e cliente; fachada A2A; roteamento a um
sistema externo. **Proposto para o exemplo:** segundo serviço FastAPI próprio
chamado `truck_info_agent`, executado como processo independente, que responde
somente consultas informativas sobre caminhões. **Extra:** múltiplos peers
cadastrados e escolhidos pelo router sem recompilar o grafo.

- Protocolo A2A 1.0.0, binding HTTP+JSON/REST, texto de entrada e saída,
  `SendMessage` síncrono, conforme `spec.md`.
- Card público mínimo em `/.well-known/agent-card.json`; chamadas de negócio
  autenticadas. Sem streaming, push ou tarefas longas no primeiro ciclo.
- Card Quistock inicialmente descreve `faq` e `product_flow` (mapeada para a
  rota local `product_workflow`). Depois da integração operacional, pode
  anunciar `truck_information` como terceira skill pública.
- O serviço de caminhões publica seu próprio card e `truck_specs` como
  primeira skill. As informações vêm de um catálogo versionado, com fonte
  recuperável para verificação.
- A integração é consultiva. Nenhum sistema A2A cria pedidos, promoções,
  decisões, alterações de estoque ou escritas comerciais.
- Perguntas com intenções misturadas que hoje exigem esclarecimento seguem
  exigindo esclarecimento; o primeiro ciclo não orquestra várias rotas em
  paralelo.

## 4. Contratos externos

### Quistock como servidor

| Operação | Contrato planejado |
|---|---|
| `GET /.well-known/agent-card.json` | Público; card A2A 1.0.0 com URL, interface REST, skills, modos e esquema de segurança. Não contém token, prompt ou dados de usuário. |
| `POST /a2a/message:send` | `SendMessage` A2A autenticado. Recebe `Message` com partes de texto e pode retornar `Message` direta no MVP. O prefixo efetivo deve coincidir com o URL do card e das rotas montadas pelo SDK. |
| Rota HTTP normal | `POST /api/v1/conversations/{conversation_id}/messages` continua chamando o mesmo `ConversationService.converse`. |

O adaptador A2A valida o envelope/protocolo, autentica o cliente e a pessoa
delegada, extrai texto de `parts`, aplica o limite atual de 4.000 caracteres,
resolve uma conversa interna autorizada, constrói `ConversationRequest` com
horário do servidor, chama `ConversationService.converse` e converte a
`ConversationResponse` em resposta A2A. Status de domínio podem ir em uma
parte de dados ou metadata versionada, além do texto. Entradas inválidas
recebem erro de protocolo/HTTP; falhas controladas do grafo preservam o
status do turno. O contrato exato de extensão precisa ser versionado.

O SDK Python A2A 1.0 oferece fábricas de rotas REST e AgentCard para montar
na FastAPI. Suas rotas não devem depender implicitamente de `Depends` das
rotas atuais: a autenticação A2A precisa ser aplicada no middleware/handler
próprio antes de chamar o executor. `ConversationService.converse` é síncrono;
se o executor SDK for assíncrono, executá-lo em threadpool limitado para não
bloquear o loop de eventos, com orçamento de tempo e cancelamento definidos.

O `contextId` é associado a `(client_id, usuário autenticado,
conversation_id)` em armazenamento durável. Na primeira chamada, o servidor
gera uma conversa e retorna um `contextId`. Em chamadas seguintes, verifica
o dono antes de restaurar memória. Continuar uma conversa ativa **não** deve
acionar `is_resuming_conversation`: esse sinal atual é para retomada de
conversa encerrada, mediante autorização explícita.

O par `(client_id, usuário, messageId)` é chave de idempotência. Reenvio da
mesma mensagem retorna o resultado registrado, sem persistir um segundo
turno. Isso requer registro atômico, pois o serviço atual gera novo
`request_id` em cada invocação. `request_id`, `trace_id`, `messageId` e
`contextId` são correlacionados, sem usar o ID do cliente como autorização.
O checkpointer `MemorySaver` atual é local ao processo; uma implantação com
vários workers precisará de checkpoint compartilhado ou de uma estratégia
explícita de afinidade/recuperação via MongoDB. Isso não é papel do A2A.

### Quistock como cliente do serviço de caminhões

1. O Quistock conhece uma URL de card configurada para `truck_info_agent`.
2. Na inicialização ou atualização controlada, obtém e valida card, versão,
   binding, skill, URL e autenticação; guarda uma cópia com prazo de cache.
3. O router escolhe `external_a2a` com `peer_id=truck_info_agent` e
   `skill_id=truck_specs`. O código valida esse par no registro.
4. O cliente envia a pergunta sanitizada em uma `Message` A2A, com
   `messageId` estável, timeout e credencial própria de serviço.
5. O adaptador valida envelope, origem, status e evidência do retorno antes
   de atualizar o `GraphState`.
6. O compilador produz um rascunho usando a evidência verificada. O juiz e o
   guardrail de saída decidem se a resposta pode ser entregue.

Para o exemplo de catálogo público de caminhões, não enviar ao peer o JWT do
usuário, email, cargo, loja, histórico completo, prompts internos ou dados
comerciais. Se uma skill futura precisar de dados privados, ela exigirá
autorização delegada própria e revisão de dados enviados.

## 5. Roteamento sem criar um sexto agente local

O router atual retorna `RouteDecision` estruturada com rotas literais. A
evolução proposta é acrescentar uma rota genérica `external_a2a` e, somente
para ela, `peer_id` e `skill_id`. O grafo ganha **um nó de integração**
`external_a2a`, não um agente adicional nem um nó para cada peer.

Exemplo de decisão estruturada, após a pergunta “Qual é a capacidade de
carga do caminhão modelo T?”:

```json
{
  "route": "external_a2a",
  "peer_id": "truck_info_agent",
  "skill_id": "truck_specs",
  "reason": "A pergunta pede uma especificação de caminhão."
}
```

O router recebe apenas candidatos autorizados para a chamada. No primeiro
ciclo, a lista contém somente a skill do peer de caminhões. O código
confere `route`, `peer_id`, `skill_id`, perfil permitido e disponibilidade
antes do envio. Uma seleção inválida vira resposta controlada; o modelo
nunca fornece URL, token, cabeçalho ou escopo de usuário.

```text
faq              → FAQ local
product_workflow → consulta comercial local autorizada
external_a2a     → cliente A2A → peer registrado → evidências → compiler
ambígua          → clarification_required
sem capacidade   → out_of_scope
```

Se o peer falha ou retorna evidência insuficiente, a rota externa termina em
resposta controlada, tal como o tratamento de indisponibilidade do Product
Workflow. Não desviar silenciosamente para FAQ nem inventar fatos.

## 6. Autenticação, autorização e isolamento

**Não há bypass A2A.** O card mínimo pode ser público. A chamada de negócio
exige identidade válida antes de entrar no grafo.

- Entrada A2A de outro sistema: credencial de serviço identifica o
  `client_id` cadastrado. Se a resposta puder usar FAQ por papel, Product
  Workflow ou memória pessoal, um contexto de usuário assinado e de curta
  duração também é obrigatório. O Quistock valida emissor, público, prazo,
  escopos e assinatura; consulta o papel atual no PostgreSQL e aplica o
  acesso à loja no repositório existente. Um email/loja no JSON não autoriza
  nada. O emissor de produção dessa delegação permanece aberto.
- Saída para o serviço de caminhões: credencial própria do Quistock perante
  o peer. O JWT humano não é encaminhado. Para o catálogo público do exemplo,
  envia-se apenas a pergunta necessária e a correlação técnica.
- O bypass já existente para testes locais por loopback não é mecanismo de
  autenticação A2A e não será habilitado em ambiente exposto.
- O Quistock atual depende de um componente anterior para impedir JWT humano
  expirado. Antes de expor o endpoint A2A fora do ambiente local, definir e
  comprovar onde essa validação ocorre; tokens de serviço/delegação devem
  sempre ter validade verificada.
- As rotas de observabilidade atuais incluem superfícies públicas de
  laboratório. Antes de publicar a aplicação externamente, restringir essas
  superfícies por autenticação ou rede. Elas não entram no AgentCard.

Para impedir ciclos entre sistemas, propagar origem, lista de peers visitados
e limite de encaminhamento. No primeiro ciclo, permitir no máximo uma chamada
A2A de saída por turno; não chamar de volta o peer que originou o turno.

## 7. Evidência remota e falhas

Uma resposta A2A é dado externo, não instrução para o Quistock. O serviço de
caminhões deve fornecer fonte original recuperável: por exemplo, registro
`truck-model-T` de um catálogo versionado, com fatos, versão/data e referência
da fonte. O adaptador confere o registro na origem permitida e verifica se
os fatos retornados correspondem à fonte. Somente então cria evidência
`source_type=a2a_agent` com `peer_id`, `source_id`, versão, frescor,
`task_id` quando existir e `trace_id`. Uma referência textual que não pode
ser verificada não basta.

`GraphState` precisará representar o resultado da integração e as novas
evidências. O compilador recebe somente fatos verificados; o juiz valida
citações e suporte; o guardrail de saída continua obrigatório. Se a fonte
não puder ser verificada, a resposta é indisponível ou insuficiente.

Prever limites configuráveis para tamanho de card, pergunta e resposta,
tempo de conexão e duração total. Um único retry pode ocorrer para timeout
ou falha transitória em leitura, usando o mesmo `messageId`; `401`, `403`,
schema inválido e pedido não idempotente não são repetidos. Registrar erro
seguro para usuário e diagnóstico sanitizado em trace. Não registrar tokens,
payload completo, prompts internos ou PII nos logs comuns.

## 8. Extra: seleção dinâmica entre vários sistemas

“Qualquer sistema” significa **qualquer peer cadastrado, compatível e
autorizado**. URL livre fornecida pelo usuário ou pelo modelo não é aceita.

1. Um administrador cadastra `peer_id`, URL do card permitida, ambiente,
   credencial, skills aprovadas, papéis/escopos, classificação de dados e
   limites. O cadastro não autentica por si só: a chamada ainda usa credencial.
2. Um processo controlado busca o AgentCard por HTTPS, valida protocolo,
   domínio/IP/redirect, tamanho, versão, autenticação e skills; armazena um
   catálogo cacheado e versionado. Cards são dados externos, não prompts.
3. Antes de cada roteamento, o servidor filtra as skills que aquele usuário
   pode usar e injeta apenas IDs e descrições curtas e sanitizadas no prompt
   do router. Esta é a variável dinâmica que o usuário mencionou.
4. O modelo devolve `route=external_a2a`, `peer_id` e `skill_id`. O servidor
   verifica novamente a escolha e resolve a URL a partir do registro, nunca
   da saída do modelo.
5. O mesmo nó `external_a2a` chama qualquer peer válido; incluir novo peer
   muda o registro e o catálogo, sem criar outra rota LangGraph.
6. O card público do Quistock anuncia apenas skills realmente oferecidas,
   permitidas e operacionais; a entrada de um peer novo exige atualizar a
   versão do catálogo/card quando sua skill passar a ser oferecida.

Sem peer elegível, o router escolhe esclarecimento ou fora de escopo. Card
malicioso, indisponível ou incompatível não entra na lista de candidatos.

## 9. Sequência de implementação e entregáveis

| Etapa | Mudança | Entregável verificável |
|---|---|---|
| 0. Fechar contrato | Confirmar o peer de demonstração, emissor da delegação, autenticação, fonte verificável, timeouts e extensão de status. Fixar versão compatível do SDK A2A 1.0 e o binding REST no projeto. | Spec atualizada, ADR de fachada/roteamento e contrato JSON. |
| 1. Serviço de caminhões | Criar aplicação independente com catálogo versionado, card e `SendMessage` protegido; retornar especificação e referência original. | Outro processo A2A funcional, consultável por cliente independente. |
| 2. Quistock servidor | Montar rotas A2A na FastAPI, card, autenticação de serviço/delegação, mapeamento de contexto, idempotência e adaptador para `ConversationService.converse`. | Cliente A2A externo obtém FAQ e Product Workflow com as mesmas regras do HTTP normal. |
| 3. Quistock cliente | Registro inicial do peer, descoberta/validação do card, cliente REST, credencial, timeout e correlação. | Quistock envia uma pergunta ao serviço de caminhões e recebe resposta protocolar. |
| 4. Grafo e evidência | Acrescentar rota `external_a2a`, nó de integração, contrato de resultado/evidência, verificação da fonte, compiler/judge/guardrail e fallback. | Pergunta de caminhão percorre o grafo inteiro e resposta sem fonte é bloqueada. |
| 5. Segurança e observabilidade | Cobrir acesso entre usuários/lojas, ciclo, replay, falhas de peer, rate limit, redaction, métricas e traces. Proteger superfícies internas antes da exposição de rede. | Demonstrações navegáveis de sucesso, `401`/`403`, timeout e evidência rejeitada. |
| 6. Extra dinâmico | Cadastro controlado e cache de múltiplos cards, filtro de skills por usuário, prompt com candidatos e resolução genérica de peer. | Segundo peer pode ser incluído sem alterar a topologia do grafo. |

Áreas prováveis do código: `src/main.py`, `src/api/routes/`,
`src/api/services/`, `src/auth/`, `src/graphs/contracts.py`,
`src/graphs/state.py`, `src/graphs/agent_graph.py`,
`src/agents/router/`, `src/graphs/adapters.py`, `src/observability/` e
um pacote novo de integração A2A. Cards internos em `src/agents/` continuam
distintos dos AgentCards do protocolo.

## 10. Requisitos e critérios de aceite

- **RF-A2A-001:** publicar card Quistock sem segredo, com skills reais.
- **RF-A2A-002:** aceitar `SendMessage` autenticado e usar o grafo atual.
- **RF-A2A-003:** vincular `contextId` e `messageId` a usuário/cliente com
  isolamento e idempotência.
- **RF-A2A-004:** permitir ao router escolher uma skill A2A externa registrada.
- **RF-A2A-005:** validar card, resposta e fonte original antes do juiz.
- **RF-A2A-006:** manter respostas controladas em falhas do peer.
- **RNF-A2A-001:** nenhum token, prompt privado ou PII desnecessária em card,
  peer ou logs comuns.
- **RNF-A2A-002:** URL, tempo, tamanho, retries e saltos limitados.
- **RNF-A2A-003:** rastrear `request_id`, `trace_id`, peer, skill e `messageId`
  nos dois sentidos, sem expor payload sensível.

Critérios observáveis:

1. Dado um cliente A2A autenticado com usuário autorizado, quando pergunta
   sobre uma regra documentada, então recebe resposta FAQ fundamentada pelo
   mesmo grafo e o turno pertence somente a esse usuário.
2. Dado um usuário sem acesso a determinada loja, quando consulta sugestão
   via A2A, então não recebe dados dessa loja.
3. Dada uma pergunta sobre o caminhão T, quando o router escolhe
   `truck_specs`, então o peer é chamado, a fonte é verificada e a resposta
   passa por compiler, juiz e guardrail.
4. Dado um `messageId` já processado, quando o cliente repete a chamada,
   então recebe o mesmo resultado sem um novo turno persistido.
5. Dado token inválido, timeout, card incompatível, loop ou fonte não
   verificável, então não há resposta factual inventada nem ampliação de
   acesso, e o trace registra a causa sanitizada.
6. Na etapa dinâmica, dado um segundo peer cadastrado com skill permitida,
   quando a pergunta corresponde à skill, então o router pode selecioná-lo
   sem adicionar outro nó ao grafo.

## 11. Decisões ainda abertas

O plano não transforma estas propostas em regras aprovadas:

1. Nome, implantação e catálogo real do serviço de caminhões; ele é o
   exemplo escolhido para planejar o primeiro peer próprio.
2. Quem emite o contexto delegado de usuário no ambiente compartilhado. O
   mock pode ter emissor controlado, mas a produção precisa de autoridade
   definida e verificação de expiração.
3. Formato versionado da extensão com status e evidências dentro da mensagem
   A2A e modo de consultar/verificar a fonte original do peer.
4. Valores de timeout, cache, rate limit e orçamento total de latência.
5. Se o Quistock anunciará `truck_information` no card público logo após a
   integração ou apenas depois da validação operacional.
6. Se a etapa dinâmica será implementada neste ciclo ou em entrega posterior;
   ela não bloqueia o caso inicial com um único peer.

## Referências

- `spec.md` e `adr-001-fachada-a2a.md` neste diretório, com as decisões A2A.
- `src/api/dependencies.py`, `src/api/services/conversation_service.py` e
  `src/graphs/agent_graph.py` para o fluxo executável.
- `docs/sdd/project-context.md` e `docs/sdd/academic-constraints.md` no
  workspace Quistock.
- [Especificação A2A 1.0.0](https://a2a-protocol.org/v1.0.0/specification/).
- [Migração do SDK Python para 1.0](https://github.com/a2aproject/a2a-python/blob/main/docs/migrations/v1_0/README.md).
