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
- Rotas protegidas do chatbot: `src/api/routes/conversation.py`, `conversation_end.py`, `conversation_history.py` e `conversation_list.py`; controllers/serviços propagam o principal.
- `src/api/routes/observability.py`: login, logout e exigência de sessão nas demais rotas da plataforma de observabilidade.
- `src/auth/observability_session.py`: sessão administrativa própria da observabilidade e configuração do cookie.
- `tests/test_observability_session.py`: cobertura da sessão e da proteção das rotas.

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

**Sessão da observabilidade**
- O chatbot mantém autenticação por JWT RS256/JWKS. A observabilidade usa um mecanismo próprio de sessão por cookie; uma identidade não substitui a outra.

**Decisão e interpretação**
- Os acessos ficam separados: o JWT identifica usuários do chatbot; o login administrativo protege a plataforma de observabilidade.
- Essa separação mantém os limites de acesso de cada superfície independentes, sem exigir mudança no fluxo JWT do chatbot para autenticar o painel.
- O trade-off é configurar e manter dois mecanismos de autenticação. Uma mudança em um fluxo não precisa alterar o outro.
- Evidências: `src/api/routes/observability.py`, `src/auth/observability_session.py` e `tests/test_observability_session.py`.
- `POST /api/v1/observability/login` valida credenciais de administrador (`super_admin`) e emite o cookie de sessão. `POST /logout` encerra essa sessão.
- O acesso fica restrito a contas `super_admin`, pois o painel reúne traces, logs e chamadas de laboratório.
- Todas as demais rotas sob `/api/v1/observability`, inclusive laboratório e feed ao vivo, exigem `require_observability_session`.
- O cookie é HTTPOnly, tem escopo limitado ao prefixo da API de observabilidade e validade de uma hora. Segredo ou dependências de autenticação ausentes fazem o fluxo falhar de forma fechada.
- A validade de uma hora equilibra a redução da janela de acesso com a conveniência de não exigir login a cada chamada.
- O cookie é `HttpOnly`: o JavaScript da página não lê seu valor, e o navegador o envia nas requisições configuradas com credenciais. Quando a sessão expira, a API responde `401` e o frontend volta à tela de login.
- **Limite do logout:** ele remove o cookie do navegador, mas não há revogação no servidor. Uma cópia do token ainda pode ser aceita até sua expiração, no máximo uma hora após o login.
- Essa é uma decisão de segurança: sem credencial de sessão ou banco, o acesso é negado para não expor dados operacionais sem autenticação. O trade-off é a observabilidade ficar indisponível enquanto a dependência estiver fora do ar.
- Os testes em `tests/test_observability_session.py` cobrem validade/configuração da sessão, login/logout, falha sem banco e exigência de sessão nas rotas. Foram inspecionados nesta análise; não foram executados.

**Limites:** a sessão da observabilidade protege as rotas desse domínio. A autenticação do chatbot continua seguindo o fluxo JWT descrito acima.

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
- **Decisão registrada:** a API mascara dados sensíveis antes de executar o grafo e restaura os valores originais somente na resposta HTTP. O mapa de restauração fica local à requisição, fora do estado e do checkpointer.
- A mensagem original não é enviada aos agentes: eles recebem a versão marcada, inclusive durante a retomada do histórico.
- Os marcadores deste turno são comparados com os marcadores da resposta. A lista permitida vem apenas da mensagem Human atual, identificada por `request_id`; marcadores antigos do histórico não autorizam reprodução.
- Se surgir marcador não presente na mensagem atual, o output guardrail troca a resposta inteira pela mensagem controlada. A resposta inteira é substituída para não deixar uma frase quebrada ao remover só o token.
- O compiler recebe uma orientação simples: quando precisar reproduzir informação escondida na mensagem atual, copiar exatamente o marcador correspondente.
- Marcadores de PII do usuário permanecem na resposta persistida. Depois do grafo, a API restaura somente marcadores presentes no mapa local e devolve o valor original na resposta HTTP; o valor restaurado não volta ao estado/checkpointer. Contatos em texto puro vindos de evidências podem ser persistidos.
- **Trade-off:** o histórico conserva o marcador, não o valor original. Isso reduz a exposição de PII persistida, mas o valor não pode ser recuperado automaticamente em uma retomada posterior.
- Não mascaramos PII em texto puro gerado na saída. Um contato presente na evidência autorizada do FAQ pode ser respondido; mascará-lo impediria esse uso legítimo. O mapa de restauração também não é ampliado com valores gerados pelo modelo.

**Saída — validações determinísticas vigentes**
1. Exige `final_response` textual; ausência ou tipo inválido usa resposta controlada.
2. Limita a resposta a 6.000 caracteres.
3. Remove emojis quando a opção está ativa.
4. Rejeita texto vazio e delimitadores Markdown desbalanceados de crase ou `**`.
5. Bloqueia as cinco frases configuradas para operações comerciais não executadas: pedido enviado, compra concluída, promoção ativada, entrega confirmada e pedido processado. Essa lista fixa não detecta toda alegação comercial sem suporte. Quando há violação, o guardrail substitui o texto por uma resposta controlada; o turno segue para persistência.
6. Não exige evidências do FAQ no output guardrail: o judge já avalia evidências e citações das respostas factuais compiladas. Mensagens diretas sem evidência são controladas, não respostas factuais do compiler.
7. Não repete no output guardrail a aprovação do judge: o grafo só encaminha resposta compilada aprovada para esse nó.

**Decisões de simplicidade e limites**
- O input guardrail usa padrões explícitos e não adiciona uma chamada de LLM; isso evita custo e latência e mantém a decisão previsível. O trade-off é cobertura limitada aos padrões implementados, sem garantir detecção de toda variação semântica.
- Cumprimentos de até 160 caracteres passam por classificador estruturado. Se a mensagem for só uma saudação, a resposta é fixa e segue para persistência sem percorrer memória, router, compiler ou judge. Isso evita acionar o restante do fluxo para um cumprimento. O trade-off é uma chamada ao modelo para classificar mensagens curtas; se ela falhar, o fluxo normal continua. Evidências: `src/guardrails/greeting.py` e `src/graphs/agent_graph.py`.
- Cada controle fica junto da fronteira que protege: entrada antes dos agentes, saída depois da compilação/julgamento. O grafo apenas conecta as etapas.
- O JEV avalia o suporte factual das respostas. O output guardrail valida formato, PII e as cinco frases operacionais explícitas quando a resposta passa por ele. Assim, as regras de saída ficam determinísticas e não repetimos uma chamada semântica de modelo.
- Quando uma validação falha, o output guardrail substitui a resposta inteira por uma frase controlada. Isso evita deixar uma violação no texto ou entregar uma resposta parcial confusa. O trade-off é descartar também partes úteis que estavam corretas.
- A substituição mantém o turno como `success` e o trace como `completed`: o usuário recebeu uma mensagem segura, compreensível e sem detalhes técnicos internos. A taxa de erros representa falhas técnicas; não contabilizar essas correções como erro é uma decisão intencional.

**Semântica dos status**
- A resposta da API pode ter `success`, `rejected`, `clarification_required`, `out_of_scope` ou `error`. Rejeição, pedido de esclarecimento e fora de escopo têm status próprios; não são `success`.
- O trace registra apenas `completed` ou `error`. Qualquer status válido da API diferente de `error` conclui o trace como `completed`.
- Falhas de modelo ou dependência podem gerar status error, assim como exceções no grafo e ausência ou invalidade de `final_response`. A resposta controlada aprovada como `success` permanece `completed` e não conta como erro técnico.
- Evidências: `src/api/schemas/conversation.py`, `src/api/services/conversation_service.py` e `src/observability/metrics.py`.
- Mantemos respostas fixas para bloqueios e falhas para não depender de geração durante uma recusa ou indisponibilidade.
- O output guardrail recebe respostas aprovadas pelo judge. Saudações isoladas e respostas terminais controladas (como entrada bloqueada, fora de escopo e judge bloqueado) seguem diretamente para `persist_turn`. Mantemos esse caminho porque essas mensagens são definidas pelo servidor; evita aplicar checagens de saída a texto fixo. O trade-off é depender de que esses caminhos continuem sem conteúdo dinâmico ou gerado por modelo.
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
- `src/memory/summaries/service.py`: escolhe busca semântica ou busca temporal no Qdrant.
- `src/memory/summaries/get_summary_context.py`: aplica filtros de usuário, status, conversa atual e intervalo temporal no Qdrant.
- `src/api/dependencies.py`: constrói o service e o injeta no `RouterExecutor`.
- `src/graphs/agent_graph.py`, `src/graphs/decisions.py` e `src/graphs/contracts.py`: registram o nó, contratos de rota e caminhos seguintes.

**Decisão de persistência da memória**
- O MongoDB guarda mensagens e metadados de conversas; Redis Streams transporta IDs de jobs de resumo; Qdrant guarda e indexa os resumos usados na recuperação.
- Essa divisão evita varrer o histórico completo do MongoDB em cada busca de contexto. O trade-off é depender da execução e indexação dos jobs para que os resumos fiquem disponíveis. Evidências: `src/memory/conversations/message_service.py`, `src/memory/jobs/summary_queue.py`, `src/memory/summaries/service.py` e `qdrant_summary_indexer.py`.

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
- **Falhas do router:** exceção do modelo, saída/rota inválida ou erro da tool não acionam uma rota improvisada. O nó registra a falha e usa resposta controlada. Isso evita adivinhar uma capacidade; o trade-off é não tentar outra rota que talvez pudesse responder.

**Regras da tool `search_conversation_summaries`**
- Única tool do router; serve apenas para referências a conversas anteriores encerradas. Não consulta FAQ, produtos nem dados comerciais.
- **Decisão de isolamento:** email, `conversation_id` e mensagem sanitizada vêm do contexto autenticado do servidor. O modelo fornece somente `start_date` e `end_date`; assim não pode escolher outra identidade ou conversa, e a ferramenta mantém um contrato estreito. O trade-off é limitar a busca às conversas do usuário autenticado. Evidências: `src/agents/router/tools/search_conversation_summaries.py` e `src/api/dependencies.py`.
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
- **Decisão confirmada:** o router classifica e escolhe uma rota; não redige a resposta final. As capacidades especializadas fornecem resultados/evidências, e o compiler compõe a resposta. Isso evita geração duplicada e mantém cada etapa com uma responsabilidade clara. Se o router falha ou retorna saída inválida, o fluxo usa resposta controlada em vez de improvisar uma rota. Evidências: `src/agents/router/executor.py`, `router_node.py`, `src/graphs/agent_graph.py` e `decisions.py`.
- Há um único nó de router ligado ao grafo e um único executor responsável pela chamada estruturada do modelo.
- A tool é opcional e estreita: o modelo não controla identidade, escopo de usuário nem SQL; o servidor aplica os filtros no Qdrant.
- **Decisão da busca:** quando há datas, o service aplica filtro temporal direto no Qdrant, sem gerar embedding; sem datas, usa similaridade semântica. Isso evita embedding desnecessário para consultas por período e usa busca semântica quando a pessoa descreve um assunto. O filtro temporal considera `updated_at` do resumo, como registrado nos limites. Evidências: `src/memory/summaries/service.py` e `src/memory/summaries/get_summary_context.py`.
- **Decisão de fallback:** sem resultado semântico, a busca pode mostrar até três resumos recentes como `recent_fallback`, identificados como contexto não confirmado. Isso oferece uma pista para retomada sem afirmar que encontrou o assunto pedido. O trade-off é que o contexto recente pode ser irrelevante; por isso, o router pede esclarecimento quando necessário.
- Validação e formatação local cobrem falhas e retomada sem criar outro agente de resposta ou rotas paralelas.

**Limites e testes relacionados**
- O limite atual é de três resumos por chamada, inclusive em períodos longos, para manter o contexto enviado ao modelo enxuto. O trade-off é poder deixar de fora uma conversa antiga relevante. A data filtra `updated_at` do resumo, não uma data extraída de cada mensagem original.
- Contratos e fluxo aparecem em `tests/test_router_graph.py`, `tests/test_router_memory_tool.py`, `tests/test_agent_executors.py`, `tests/test_agent_graph.py` e `tests/integration/test_router_graph_integration.py`.
- Esta análise documenta o código presente; os testes não foram executados nesta alteração.

## Análise 4 — FAQ/RAG

**Objetivo:** responder dúvidas documentadas com trechos recuperados da base autorizada, sem completar lacunas com conhecimento próprio do modelo.

**Arquivos centrais**
- `src/agents/faq/card.py` e `faq_prompt.py`: declaram a capacidade do agente, sua única ferramenta e as regras de uso das evidências.
- `src/agents/faq/executor.py`: cria o agente por turno, injeta a busca com escopo autorizado e valida o resultado da ferramenta.
- `src/agents/faq/faq_node.py`: deriva as audiências do cargo autenticado, projeta evidências no grafo e trata ausência ou falha.
- `src/agents/faq/tools/faq_tool.py` e `schemas.py`: executam a consulta e validam o envelope, os resultados e o desfecho `not_found`.
- `src/agents/faq/retrieval/qdrant_retriever.py`: aplica o filtro de audiência durante a busca vetorial.
- `tests/test_faq_role_filter.py`, `tests/test_faq_tools.py` e `tests/integration/test_faq_no_evidence_graph_integration.py`: cobrem escopo por cargo, ausência de resultados e caminho pelo grafo.

**Decisões e interpretação**
- **Decisão confirmada:** o FAQ consulta documentos indexados no Qdrant. A aplicação define o escopo a partir do cargo autenticado: conteúdo compartilhado e conteúdo do cargo correspondente. A pergunta do usuário não pode escolher cargo nem ampliar esse acesso.
- A ferramenta registra `not_found` com evidência explícita quando a busca não encontra trechos. O fluxo informa que não encontrou informação documentada; não trata ausência como falha técnica nem permite completar a resposta por conhecimento próprio.
- Quando há resultados, o agente deve responder apenas com os trechos recuperados e indicar a fonte. Consulta sem resultado continua pelo compiler e pelo judge, que recebem a ausência explícita como evidência.
- Essa organização mantém recuperação, escopo de acesso e composição da resposta em pontos distintos. O runtime constrói a ferramenta autorizada por requisição, sem guardar o cargo em estado global.

**Trade-off e limites**
- Respostas ficam limitadas ao acervo indexado e à relevância dos trechos recuperados. Um documento ausente ou não recuperado pode produzir `not_found`, mesmo que a informação exista fora da base.
- O FAQ não consulta dados comerciais em tempo real nem outras fontes externas. Perguntas que dependem dessas capacidades devem seguir a rota própria.
- Os testes citados foram inspecionados nesta análise; não foram executados nesta alteração.

## Análise 5 — Product Workflow

**Objetivo:** consultar informações comerciais autorizadas sobre sugestões e promoções para responder às perguntas do usuário.

**Arquivos centrais**
- `src/agents/product_workflow/card.py`: declara a capacidade e as ferramentas comerciais disponíveis ao agente.
- `src/agents/product_workflow/executor.py`: valida o contexto da requisição, monta as ferramentas permitidas e executa o agente.
- `src/agents/product_workflow/repository.py`: concentra as consultas ao PostgreSQL comercial.
- `src/agents/product_workflow/filters.py` e `tools/`: definem filtros e operações de consulta expostas ao agente.
- `src/agents/product_workflow/product_workflow_node.py`: integra o resultado e as evidências ao grafo.
- `tests/test_product_workflow.py` e `tests/test_product_workflow_repository.py`: cobrem o agente e as consultas do repositório.

**Decisão confirmada**
- O Product Workflow é somente leitura: consulta sugestões e promoções, mas não cria pedidos nem altera dados comerciais.
- **Decisão confirmada de visibilidade:** as consultas incluem somente sugestões `ORDER` e `PROMOTION` autorizadas para o usuário, associadas a lojas e produtos ativos e sem evento `EXPIRED`. Os filtros ficam no repositório, não dependem da interpretação do modelo. Evidências: `src/agents/product_workflow/filters.py`, `repository.py` e testes do repositório.
- **Decisão confirmada de paginação:** cada listagem apresenta até seis itens; a numeração continua entre páginas e o fluxo só consulta outra página quando o usuário pede. Isso mantém cada resposta e contexto menores; o trade-off é exigir mais interações para percorrer listas extensas. Evidências: `src/agents/product_workflow/tools/schemas.py`, `list_suggestions.py`, `src/agents/product_workflow/product_workflow_node.py` e `tests/test_product_workflow.py`.
- **Escolha numerada:** quando o usuário escolhe um item, o agente repete a consulta na página e no tipo corretos para obter a referência da opção; a ferramenta de detalhe então consulta o repositório e valida novamente a seleção e seu escopo antes de devolver o card. A validação extra reduz o risco de exibir uma opção alterada ou fora do escopo. O trade-off é uma consulta adicional ao banco. Evidências: `src/agents/product_workflow/product_workflow_prompt.py`, `tools/get_suggestion_detail.py`, `tools/schemas.py` e `tests/test_product_workflow.py`.
- **Decisão confirmada sobre datas relativas:** o executor usa `request.sent_at` convertido para `America/Sao_Paulo` como data local da mensagem ao interpretar prazos. Se `sent_at` não estiver disponível, usa a data local atual. Isso mantém a referência alinhada ao turno quando há timestamp; o fallback evita interromper a consulta sem ele. Evidências: `src/agents/product_workflow/executor.py` e `product_workflow_prompt.py`.
- **Decisão confirmada sobre o filtro `until`:** quando o usuário informa uma data final, a busca lista promoções com validade entre a data de referência da mensagem e a data final, inclusive. Esse filtro define um intervalo e não é combinado com o critério de validade `nearest` ou `longest`. Evidências: `src/agents/product_workflow/tools/get_promotion_by_expiration.py` e `repository.py`.
- **Decisão confirmada sobre validade extrema:** sem data final, `nearest` busca a menor data de validade a partir da data de referência; `longest` busca a maior, sempre dentro do escopo autorizado. Evidências: `src/agents/product_workflow/tools/get_promotion_by_expiration.py` e `repository.py`.
- **Decisão confirmada de autorização:** usuário, cargo e lojas vêm do contexto autenticado e são aplicados pelo servidor. O agente não escolhe outra identidade nem envia SQL livre.
- **Decisão confirmada sobre a quantidade nas sugestões consultadas no banco:** para `ORDER`, a API de IA usa somente `current_batch_count`; `ml_batch_count` foi removido da consulta, do DTO e do card público na PR #46. A escolha evita misturar uma estimativa de ML com a quantidade atual e reduz a ambiguidade para o usuário. Se `current_batch_count` estiver ausente, o fluxo não usa outro campo como fallback nem inventa uma quantidade. O `batch_count` de um `product_card` enviado pelo cliente é um dado separado do snapshot e não substitui a quantidade da consulta SQL. Evidências: PR #46; `src/agents/product_workflow/contracts.py`, `repository.py`, `tools/schemas.py` e `product_workflow_prompt.py`.
- **Trade-off:** o modelo deixa de apresentar a estimativa de ML. Quando a quantidade atual não estiver disponível, a resposta não mostrará quantidade em vez de inferi-la.
- O executor valida esse contexto antes de habilitar as ferramentas; o repositório aplica os parâmetros e predicados fixos de cargo e loja nas consultas. Isso mantém a consulta dentro do escopo concedido ao usuário. O trade-off é que somente os cargos e lojas autorizados podem usar a capacidade. Evidências: `src/agents/product_workflow/executor.py`, `repository.py` e `filters.py`.
- Essa separação deixa as respostas consultivas sem autorização para executar operações comerciais. As alterações de negócio permanecem fora desta capacidade.
- **Trade-off:** o fluxo pode explicar o que está registrado, mas não conclui a operação pelo usuário.

**Limite da análise:** os testes citados não foram executados nesta alteração.
