# JUSTIFICATIVAS

## Análise 1 — Autenticação e autorização

**Escopo:** como a API autentica a identidade do usuário e autoriza o acesso às capacidades de conversa. O cliente não define `user_id`, `email`, cargo ou lojas.

**Fluxo:** `Authorization: Bearer <JWT>` → `HTTPBearer` → validação do JWT → consulta da conta → `AuthenticationService` → `AuthenticatedPrincipal` → capacidades.

**Arquivos centrais**
- `src/api/dependencies.py`: recebe Bearer e compõe o fluxo; traduz falhas em HTTP.
- `src/auth/token.py`: valida assinatura e claims do JWT; retorna `VerifiedToken`.
- `src/auth/account_repository.py`: consulta conta, cargo e vínculos com lojas usando SQL parametrizado.
- `src/auth/service.py`: confere conta e aplica a política geral de autorização.
- `src/auth/models.py`, `permissions.py` e `errors.py`: contratos, cargos permitidos e falhas tipadas.
- `src/auth/postgres.py`, `src/config.py` e `src/main.py`: pool, configurações e ciclo de vida do pool em `app.state`.
- `.env.example`: documenta ambiente; não contém mais configurações de bypass.
- Rotas protegidas: `src/api/routes/conversation.py`, `conversation_end.py`, `conversation_history.py` e `conversation_list.py`; controllers/serviços propagam o principal.

**Validações do JWT**
- Exige RS256, chave `kid` do JWKS, issuer `iss` e audience `aud` exatamente `["quistock-api"]`.
- Exige `sub`, `email`, `iss`, `aud`, `iat`, `exp` e `jti`; exige `exp - iat = 300 s`, `sub` numérico válido e `email`/`jti` não vazios.
- `jti` permanece obrigatório no contrato, mas não é usado para revogação ou prevenção de reuso.

**Validações da conta e autorização**
- Busca a conta pelo `sub`; exige conta existente e `ACTIVE`, e-mail do JWT exatamente igual ao do banco, cargo `MANAGER` ou `EMPLOYEE` e pelo menos uma loja ativa.
- A consulta é parametrizada, limita a duração, filtra vínculos/lojas ativos e elimina lojas duplicadas. O principal usa dados do banco.
- FAQ filtra audiências por cargo (`src/agents/faq/executor.py`, `retrieval/qdrant_retriever.py`); Product Workflow restringe cargo/lojas (`src/agents/product_workflow/executor.py`, `models.py`, `filters.py`, `repository.py`).
- Conversas e retomada restringem proprietário/status (`src/memory/mongo_repository.py`, `get_summary_context.py`). Essas checagens por capacidade são defesa em profundidade.

**Falhas e cobertura**
- Credencial inválida, conta ausente/inativa ou e-mail divergente: `401`; cargo/lojas sem acesso: `403`; JWKS indisponível: `503`; configuração ou banco indisponível: `500`.
- `src/observability/audit.py` registra motivos sem JWT ou identidade. Testes de contrato: `tests/test_auth_token.py`, `test_auth_repository.py`, `test_auth_dependency.py`, `test_auth_audit.py` e `tests/integration/test_auth_postgres.py`.
- O teste de dependência exige `401` também em loopback sem token. Testes não foram executados nesta análise.

**Limites:** bypass e verificação de loopback foram removidos do checkout principal. `src/api/routes/observability.py` não usa esta dependência; sua política fica para a revisão da API.

## Análise 2 — Guardrails de entrada e saída

**Objetivo:** aplicar controles locais, explícitos e de baixo custo antes de chamar agentes e antes de liberar respostas compiladas. Guardrails não substituem autorização nem o judge de evidências.

**Arquivos que compõem o fluxo**
- `src/guardrails/input.py`: valida entrada e aplica bloqueios determinísticos.
- `src/guardrails/output.py`: valida a forma da resposta e os marcadores PII.
- `src/guardrails/pii.py`: detecta formatos de PII, cria marcadores, mantém funções de restauração.
- `src/guardrails/greeting.py`: classifica possíveis saudações curtas; não redige respostas.
- `src/guardrails/config.py`: concentra limites, opções ativas e contratos tipados.
- `src/api/services/conversation_service.py`: mascara PII antes do grafo, mantém o mapa local à requisição e restaura marcadores somente para a resposta HTTP.
- `src/graphs/agent_graph.py`, `decisions.py` e `adapters.py`: conectam os nós e determinam os caminhos.
- `src/agents/compiler/compiler_prompt.py`, `src/agents/judge/executor.py`: orientam a reprodução de marcadores e avaliam suporte factual do conteúdo compilado.

**Entrada — ordem e regras**
1. A API mascara CPF, CNPJ, e-mail, telefone, cartão e credenciais antes de criar o estado do grafo.
2. Os marcadores seguem `[DADO_SENSIVEL_{TIPO}_{REQUEST_ID}_{SEQUENCIA}]`; o mapa com valores originais fica em variável local da requisição, fora do estado/checkpointer.
3. `input_guardrail` rejeita mensagem vazia e mais de 4.000 caracteres, medidos pelo tamanho original recebido pela API.
4. Em seguida verifica padrões determinísticos de prompt injection, pedidos por dados internos e política governamental.
5. Entrada bloqueada recebe resposta controlada; o histórico guarda `[ENTRADA_BLOQUEADA]`, não o texto original. O bloqueio não chama greeting, router, compiler, judge nem tools.
6. Não há classificação semântica por LLM no input guardrail. Essa escolha evita custo, latência e decisões variáveis para regras que já têm critérios explícitos.
7. Após entrada aprovada, `greeting_guardrail` usa LLM estruturado apenas para mensagens de até 160 caracteres. Se for apenas saudação, a resposta é fixa; se não, segue ao fluxo normal. Mensagens maiores seguem sem chamada do classificador.

**PII — privacidade e restauração**
- A mensagem original não é enviada aos agentes: eles recebem a versão marcada, inclusive durante a retomada do histórico.
- Os marcadores deste turno são comparados com os marcadores da resposta. A lista permitida vem apenas da mensagem Human atual, identificada por `request_id`; marcadores antigos do histórico não autorizam reprodução.
- Se surgir marcador não presente na mensagem atual, o output guardrail troca a resposta inteira pela mensagem controlada. A resposta inteira é substituída para não deixar uma frase quebrada ao remover só o token.
- O compiler recebe uma orientação simples: quando precisar reproduzir informação escondida na mensagem atual, copiar exatamente o marcador correspondente.
- Marcadores de PII do usuário permanecem na resposta persistida. Depois do grafo, a API restaura somente marcadores presentes no mapa local e devolve o valor original na resposta HTTP; o valor restaurado não volta ao estado/checkpointer. Contatos em texto puro vindos de evidências podem ser persistidos.
- Não mascaramos PII em texto puro gerado na saída. Um contato presente na evidência autorizada do FAQ pode ser respondido; mascará-lo impediria esse uso legítimo. O mapa de restauração também não é ampliado com valores gerados pelo modelo.

**Saída — validações determinísticas vigentes**
1. Exige `final_response` textual; ausência ou tipo inválido usa resposta controlada.
2. Limita a resposta a 6.000 caracteres.
3. Remove emojis quando a opção está ativa.
4. Rejeita texto vazio e delimitadores Markdown desbalanceados de crase ou `**`.
5. Bloqueia frases que afirmam operações comerciais não executadas: pedido enviado, compra concluída, promoção ativada, entrega confirmada ou pedido processado.
6. Não exige evidências do FAQ no output guardrail: o judge já avalia evidências e citações das respostas factuais compiladas. Mensagens diretas sem evidência são controladas, não respostas factuais do compiler.
7. Não repete no output guardrail a aprovação do judge: o grafo só encaminha resposta compilada aprovada para esse nó.

**Decisões de simplicidade e limites**
- A validação usa padrões, limites e listas pequenas mantidas no código; não adicionamos outro LLM para decidir segurança na entrada ou compliance na saída.
- Cada controle fica junto da fronteira que protege: entrada antes dos agentes, saída depois da compilação/julgamento. O grafo apenas conecta as etapas.
- O judge é a única revisão semântica de suporte factual da resposta compilada; assim não duplicamos a mesma regra no guardrail.
- Mantemos respostas fixas para bloqueios e falhas para não depender de geração durante uma recusa ou indisponibilidade.
- O output guardrail atualmente atende saudação e resposta compilada aprovada. Algumas rotas controladas terminam diretamente em `persist_turn`; unificá-las no output guardrail é uma alteração de grafo separada, não incluída nesta análise.
- `pipeline.py`, as fachadas `input_guardrail.py`/`output_guardrail.py`, `GuardrailResult` e `timeout_ms` sem uso foram removidos. A API e o grafo importam os nós diretamente dos módulos `input.py` e `output.py`.
- Os testes relacionados estão em `tests/test_input_guardrail.py`, `tests/test_output_guardrail.py`, `tests/test_greeting_classifier.py`, `tests/test_agent_graph.py` e `tests/integration/test_guardrails_integration.py`; não foram executados nesta análise.


## Análise 3 — Router: roteamento e retomada de conversas

**Objetivo:** escolher uma rota permitida com uma saída estruturada, sem redigir a resposta especializada. O router também pode recuperar contexto anterior quando isso é necessário para resolver a solicitação.

**Arquivos centrais**
- `src/agents/router/card.py`: declara identidade, prompt e a única tool possível do router.
- `src/agents/router/router_prompt.py`: define rotas, quando consultar memória e como interpretar datas mencionadas.
- `src/agents/router/executor.py`: monta mensagens para o modelo, registra tool disponível por requisição e normaliza a resposta estruturada.
- `src/agents/router/router_node.py`: valida a resposta do executor, projeta evidências e erros no estado, e direciona a decisão do router.
- `src/agents/router/tools/schemas.py`: limita os argumentos de data da tool e valida o intervalo.
- `src/agents/router/tools/search_conversation_summaries.py`: vincula identidade e mensagem do contexto autenticado, chama o service e empacota resultados como evidências.
- `src/memory/service.py`: escolhe busca semântica ou busca temporal no Qdrant.
- `src/memory/get_summary_context.py`: aplica filtros de usuário, status, conversa atual e intervalo temporal no Qdrant.
- `src/api/dependencies.py`: constrói o service e o injeta no `RouterExecutor`.
- `src/graphs/agent_graph.py`, `src/graphs/decisions.py` e `src/graphs/contracts.py`: registram o nó, contratos de rota e caminhos seguintes.

**Fluxo executável**
1. O grafo envia a mensagem sanitizada ao nó `router`, implementado por `run_router_node`.
2. O nó chama `RouterExecutor.invoke`; o modelo retorna `RouteDecision` com rota e justificativa curta.
3. O executor injeta a data local atual (`America/Sao_Paulo`) como `SystemMessage`, para o modelo resolver datas relativas naquele turno.
4. Se houver card de produto válido, o executor acrescenta ao contexto apenas nome, SKU e categoria, tratados como dado auxiliar.
5. O executor constrói a tool somente se o service estiver injetado e se identidade, conversa e mensagem atual forem válidas. O card de runtime mantém somente bindings das tools realmente disponíveis.
6. `router_node` valida contrato, rota, status, justificativa e envelope/evidências da tool antes de atualizar `GraphState`.
7. O grafo encaminha `faq` e `product_workflow` às capacidades ativas. `memory_recall` retorna resposta local do router; esclarecimento e fora de escopo seguem por caminhos controlados.

**Rotas e responsabilidade**
- Rotas estruturadas: `faq`, `product_workflow`, `memory_recall`, `clarification_required` e `out_of_scope`.
- `RouteResponse` pode carregar `tool_called` e `error_code` na fronteira do executor. `RoutingDecision` no estado não carrega esses campos; evidências vão para `GraphState.evidences` e erros técnicos para `state.errors`.
- `router_node` mapeia `faq`/`product_workflow` para despacho, `clarification_required` e `out_of_scope` para seus resultados controlados, e `memory_recall` para resposta direta.
- O executor e o nó não delegam resposta factual ao router. O router classifica; FAQ/Product Workflow respondem por suas capacidades, e o compiler/judge atuam depois quando aplicável.
- Exceção do modelo, resposta estruturada inválida, rota inválida, erro da tool ou busca sem resultados não são tratados como sucesso factual. O nó registra falha e usa resposta controlada quando necessário.

**Regras da tool `search_conversation_summaries`**
- Única tool do router; serve apenas para referências a conversas anteriores encerradas. Não consulta FAQ, produtos nem dados comerciais.
- A identidade autenticada, `conversation_id` e mensagem sanitizada são vinculadas no servidor. O modelo fornece somente os argumentos visíveis `start_date` e `end_date`.
- As duas datas devem ser informadas juntas ou omitidas juntas. Para uma data única, o prompt instrui o modelo a enviar a mesma data nos dois campos. Intervalo invertido é rejeitado.
- O router converte datas relativas usando a data atual injetada no turno; se o ano faltar, usa o ano atual; se somente o dia do mês for informado, usa o mês e ano atuais. O service não interpreta texto de data.
- Com intervalo, o service converte o período civil inclusivo de `America/Sao_Paulo` em limites datetime e chama `scroll`, sem embedding. O limite superior é a meia-noite após `end_date`, exclusiva no filtro.
- Sem intervalo, o service faz busca semântica com embedding e score mínimo configurado. Sem resultado relevante, pode retornar até três conversas recentes identificadas como `recent_fallback`.
- Os filtros Qdrant restringem ao email autenticado, status `ended` e excluem a conversa atual. A consulta temporal filtra `updated_at` e ordena do mais recente para o mais antigo.
- A tool serializa até três resumos e inclui evidência por resultado, com origem temporal, semântica ou `recent_fallback`. Resultado vazio recebe evidência `not_found` no executor para manter a ausência explícita.
- Erros de dependência são convertidos em resultado seguro da tool; `router_node` mantém o erro técnico internamente e não expõe detalhes do banco ao usuário.
- Resultados e evidências são capturados pelo executor mesmo quando o modelo falha depois de chamar a tool; o nó ainda pode projetar essas evidências no estado.

**Resposta local de retomada**
- Para resultados de memória, `router_node` forma resposta a partir das evidências, usando no máximo três tópicos e até 250 caracteres por tópico.
- `recent_fallback` é apresentado como contexto recente não confirmado como correspondência temática; se não houver evidência útil, o usuário recebe pedido de esclarecimento.
- Essa resposta evita uma segunda chamada de modelo para resumir a saída já estruturada da busca. A memória serve para resolver contexto, não para substituir evidência atual de FAQ ou produto.

**Por que a composição é simples e eficiente**
- Há um único nó de router ligado ao grafo e um único executor responsável pela chamada estruturada do modelo.
- A tool é opcional e estreita: o modelo não controla identidade, escopo de usuário nem SQL; o servidor aplica os filtros no Qdrant.
- A data já resolvida vira filtro temporal direto; não há parsing de datas dentro do service nem geração de embedding para consultas por período.
- Sem data, a busca semântica existente permanece disponível; o fallback recente é explicitamente identificado, evitando afirmar correspondência que não foi encontrada.
- Validação e formatação local cobrem falhas e retomada sem criar outro agente de resposta ou rotas paralelas.

**Limites e testes relacionados**
- O limite atual é de três resumos por chamada, inclusive em períodos longos. A data filtra `updated_at` do resumo, não uma data extraída de cada mensagem original.
- Contratos e fluxo aparecem em `tests/test_router_graph.py`, `tests/test_router_memory_tool.py`, `tests/test_agent_executors.py`, `tests/test_agent_graph.py` e `tests/integration/test_router_graph_integration.py`.
- Esta análise documenta o código presente; os testes não foram executados nesta alteração.
