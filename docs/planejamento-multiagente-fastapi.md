# Planejamento do sistema multiagente e da API FastAPI

**Status:** planejamento, sem implementação

**Última atualização:** 2026-08-13

## Objetivo

Planejar a evolução do sistema atual para uma API FastAPI baseada em LangChain e LangGraph, mantendo o agente FAQ/RAG e adicionando um agente especializado em produtos e fluxos.

O sistema será utilizado por um aplicativo que sugere produtos para pedido, promoção ou nenhuma ação, conforme o fluxo informado por um modelo de Machine Learning.

## Decisões confirmadas

### Classificação de produtos

Um produto pode ser classificado pelo modelo de Machine Learning em três fluxos:

- **Alto:** produto candidato a sugestão de pedido.
- **Baixo:** produto candidato a sugestão de promoção.
- **Normal:** não gera sugestão.

A classificação será baseada na frequência de venda e compra.

O desenvolvimento, treinamento e operação do modelo de Machine Learning serão independentes dos agentes. Os agentes não treinam, executam ou recalculam o modelo.

O modelo poderá atualizar os resultados diariamente ou semanalmente. Cada atualização deve ser identificável por uma versão ou execução, para que uma resposta possa informar qual análise foi consultada.

### Escopo do aplicativo

Na primeira versão, o aplicativo:

- consulta as listas de produtos por fluxo;
- sugere pedido ou promoção;
- explica por que um produto está ou não está em determinada lista;
- pode realizar simulações;
- não executa pedidos nem cria promoções.

Qualquer operação real será um fluxo futuro, com autorização específica.

### Usuários

Os perfis previstos são:

- funcionário;
- gerente;
- gerente regional.

Na primeira versão, todos os perfis ficam restritos a consulta e simulação, respeitando permissões futuras. A possibilidade de um gerente executar operações pertence a outro fluxo e não faz parte deste planejamento inicial.

### Dados manuais

Substituições manuais, correções ou decisões administrativas sobre a classificação serão tratadas em um fluxo separado, realizado por gerente ou gerente regional. O agente de consulta não deve alterar a análise do ML.

### Indisponibilidade

Quando os dados necessários, o agente ou uma integração estiver indisponível, a API deve retornar uma resposta controlada de indisponibilidade. O sistema não deve inventar classificação, motivo ou recomendação.

### Retenção

O histórico de mensagens e os registros de execução deverão ser mantidos por aproximadamente três dias, sujeito a confirmação de requisitos legais, segurança e operação.

### Forma de resposta

A primeira versão da API será síncrona. Streaming, provavelmente via SSE, poderá ser adicionado posteriormente.

## Agentes

### Agente FAQ/RAG existente

Responsável por responder informações contidas exclusivamente nos documentos da base RAG.

Regras preservadas:

- consultar a base quando a pergunta envolver documentação, políticas ou processos;
- citar o arquivo de origem;
- informar quando não encontrar a resposta;
- não inventar informações;
- responder em português.

Esse agente não deve usar a tabela de análise de produtos para responder perguntas que pertencem ao agente de fluxo.

### Agente Product Flow Advisor

Responsável por orientar e informar sobre:

- fluxo alto, baixo ou normal;
- produtos presentes em cada lista;
- sugestão de pedido;
- sugestão de promoção;
- motivo de um produto não estar na lista de pedido;
- motivo de um produto não estar na lista de promoção;
- data, período e versão da análise consultada.

O agente consulta dados estruturados e explica os resultados em linguagem natural. Ele não deve reinterpretar a previsão do ML nem criar regras comerciais novas.

### Segundo agente futuro

O segundo agente não será implementado agora. A hipótese recomendada é um **Agente de Operações Comerciais**, responsável por simular e, futuramente, encaminhar operações mediante confirmação e autorização.

Esse agente exigirá regras próprias de permissão, confirmação explícita, auditoria, tratamento de erro e eventual rollback. Ele não deve ser misturado ao Product Flow Advisor.

## Fonte de verdade das recomendações

O LLM não deve ser a fonte de verdade da lista de produtos.

O fluxo conceitual é:

```text
Modelo de Machine Learning
        ↓
Tabela de métricas e previsões
        ↓
Tabela/listagem de análise por fluxo
        ↓
Consulta estruturada do aplicativo
        ↓
Agente explica o resultado ao usuário
```

O aplicativo poderá consumir diretamente a listagem estruturada. O chatbot será utilizado para consulta, explicação e simulação, não para substituir a regra determinística.

## Dados de negócio necessários

### Catálogo de produtos

Deve identificar o produto de forma estável e conter, no mínimo:

- identificador;
- SKU ou código operacional;
- nome;
- categoria;
- status ativo/inativo.

### Resultado do Machine Learning

Deve representar a saída do modelo, incluindo:

- produto;
- fluxo previsto;
- confiança ou score fornecido pelo modelo;
- período de venda e compra analisado;
- data de geração;
- versão do modelo;
- identificador da execução;
- status de qualidade ou disponibilidade.

O agente apenas apresenta ou utiliza a saída publicada. Não cabe a ele decidir se a confiança é suficiente.

### Análise e listagem por fluxo

Deve permitir responder:

- em qual fluxo o produto está;
- em qual listagem ele aparece;
- se é candidato a pedido;
- se é candidato a promoção;
- por que não é candidato a uma determinada ação;
- qual versão da análise gerou o resultado.

Os motivos devem preferencialmente possuir códigos estruturados, como `FLUXO_NORMAL`, `NAO_ELEGIVEL_PARA_PEDIDO`, `DADO_INDISPONIVEL` ou `PRODUTO_INATIVO`. O texto amigável pode ser montado pelo agente a partir desses dados.

## Fluxos do LangGraph

### Fluxo geral

```text
Mensagem da API
    ↓
Carregamento/criação da sessão
    ↓
Guardrail de entrada
    ↓
Roteador
    ↓
Agente ou serviço especializado
    ↓
Validação da resposta do agente
    ↓
Compilador, quando houver múltiplos resultados
    ↓
Guardrail final
    ↓
Persistência da resposta
    ↓
Resposta síncrona da API
```

### Branch A — Entrada inválida

```text
Guardrail de entrada
    ↓
Mensagem inválida, insegura ou fora do escopo
    ↓
Resposta controlada
```

Nenhum agente especializado deve ser chamado nesse caso.

### Branch B — Pergunta de FAQ

```text
Roteador
    ↓
Agente FAQ/RAG
    ↓
Validação de fonte e escopo
    ↓
Resposta
```

### Branch C — Consulta de fluxo

```text
Roteador
    ↓
Product Flow Advisor
    ↓
Consulta ao catálogo e à análise vigente
    ↓
Resposta com fluxo, consequência e versão da análise
```

### Branch D — Motivo de não estar em promoção

```text
Roteador
    ↓
Product Flow Advisor
    ↓
Consulta do produto
    ↓
Consulta de elegibilidade para promoção
    ↓
Consulta do motivo estruturado
    ↓
Explicação ao usuário
```

Se o motivo não estiver disponível, o agente deve informar a indisponibilidade e não deduzir a causa.

### Branch E — Motivo de não estar em pedido

Mesmo fluxo da Branch D, consultando a elegibilidade e o motivo relativos a pedido.

### Branch F — Pedido de recomendações

```text
Roteador
    ↓
Consulta estruturada da listagem vigente
    ↓
Product Flow Advisor ou formatador
    ↓
Resposta com produtos e ações sugeridas
```

### Branch G — Pergunta ambígua

```text
Roteador
    ↓
Solicitação de esclarecimento
```

Exemplo: perguntar se o usuário deseja entender a ausência na lista de pedido ou na lista de promoção.

### Branch H — Múltiplas intenções

Perguntas independentes podem ser divididas e executadas em paralelo. Os resultados devem ser reunidos pelo compilador sem que um agente sobrescreva a resposta do outro.

## Guardrails, validação e compilação

O conceito de “guardrail de saída” deve ser dividido em duas etapas:

1. **Validação das respostas dos agentes:** verifica escopo, evidências, fontes e contrato de saída.
2. **Guardrail final:** verifica segurança, privacidade, consistência e exposição indevida antes de responder ao usuário.

O compilador fica entre essas duas etapas.

O compilador não deve criar fatos. Ele apenas combina, organiza e simplifica resultados já validados.

## Estado compartilhado

O estado do LangGraph deve separar controle de fluxo, dados de negócio e observabilidade.

### Sessão

- identificador da sessão;
- usuário e perfil;
- origem da requisição;
- data de criação;
- data da última atividade;
- política de retenção.

### Turno da conversa

- identificador da mensagem;
- texto do usuário;
- texto normalizado;
- resposta final;
- status do turno;
- timestamps.

### Segurança

- resultado do guardrail de entrada;
- resultado da validação dos agentes;
- resultado do guardrail final;
- flags de privacidade e segurança.

### Roteamento

- intenção;
- entidades identificadas;
- rota escolhida;
- agentes chamados;
- motivo da rota;
- status da execução.

### Dados de negócio

- produtos identificados;
- fluxos consultados;
- listagens retornadas;
- motivos estruturados;
- versão da análise;
- confiança ou score publicado pelo ML, quando disponível.

### Evidências

- fonte;
- tipo da fonte;
- identificador do registro;
- período;
- versão;
- trecho ou resumo permitido para auditoria.

### Resultados dos agentes

Cada agente deve escrever em seu próprio espaço lógico, evitando sobrescrita entre agentes.

### Observabilidade

- eventos de execução;
- chamadas de ferramentas;
- erros;
- latência;
- tokens;
- modelo;
- versão do prompt;
- identificadores de correlação.

Listas de mensagens, eventos, evidências e chamadas de ferramentas devem ser append-only e possuir regra de merge quando houver paralelismo.

## Persistência e análise de sessões

Serão necessários dois níveis:

### Checkpoint operacional

Utilizado pelo LangGraph para retomar ou recuperar uma execução interrompida.

### Registro analítico

Utilizado pelos desenvolvedores para investigar:

- timeline da sessão;
- agentes chamados;
- decisões de roteamento;
- ferramentas utilizadas;
- fontes consultadas;
- falhas;
- latência;
- respostas geradas.

O “pensamento” bruto do modelo não deve ser persistido. Deve ser armazenado um registro estruturado do comportamento observável: plano, ferramentas, evidências, decisão, validações e erros.

## Observabilidade: alternativas

### Opção 1 — LangSmith

Boa opção para desenvolvimento com LangChain e LangGraph, pois facilita inspeção de runs, nós, ferramentas, prompts e latência.

Ponto de atenção: avaliar envio de dados sensíveis para um serviço externo e configurar mascaramento ou retenção adequada.

### Opção 2 — OpenTelemetry com Grafana

Opção mais flexível para uma plataforma própria, utilizando traces, métricas e logs correlacionados.

Pode ser combinada com:

- Grafana Tempo para traces;
- Grafana Loki para logs;
- Prometheus para métricas.

Ponto de atenção: exige mais configuração e manutenção.

### Opção 3 — Sentry com logs estruturados

Boa para erros, exceções e alertas da API, complementada por armazenamento próprio da timeline das sessões.

Ponto de atenção: não substitui sozinho a visualização detalhada do grafo multiagente.

### Recomendação para o projeto

Para a primeira fase de desenvolvimento, utilizar uma solução de tracing especializada em LangChain/LangGraph, como LangSmith, desde que a política de dados permita.

Para uma evolução mais controlada e independente, migrar ou complementar com OpenTelemetry, Sentry e armazenamento próprio de eventos.

Essa decisão deve considerar custo, hospedagem, privacidade, acesso dos desenvolvedores e volume de sessões.

## API FastAPI

A FastAPI deve cuidar de transporte, autenticação, validação de entrada, ciclo de vida da sessão e resposta HTTP. A lógica de orquestração deve permanecer em serviços e no grafo LangGraph.

Endpoints conceituais da primeira versão:

- criação de sessão;
- envio de mensagem;
- consulta do histórico;
- consulta do estado resumido da sessão;
- health check;
- readiness check.

Endpoints analíticos devem ficar protegidos para desenvolvedores ou administradores e não devem expor o trace interno aos usuários comuns.

A primeira versão será síncrona. Streaming poderá ser adicionado depois sem alterar as regras de negócio principais.

## Retenção e privacidade

O prazo inicial de retenção é de aproximadamente três dias. Antes da implementação, devem ser definidos:

- quais dados do usuário são sensíveis;
- quais campos devem ser mascarados;
- quem pode consultar o histórico;
- quem pode consultar traces;
- se mensagens completas serão armazenadas;
- como ocorre a exclusão antecipada;
- como logs e traces serão removidos junto com a sessão.

## Critérios de sucesso do Product Flow Advisor

A pergunta 16 foi convertida nos seguintes critérios:

- identifica corretamente perguntas sobre fluxo;
- diferencia pedido, promoção e ausência de sugestão;
- informa a fonte e a versão da análise;
- explica a ausência de um produto somente quando existe motivo registrado;
- não inventa motivos quando os dados estão ausentes;
- respeita o perfil do usuário;
- não executa operações;
- sinaliza indisponibilidade quando uma integração não responde;
- mantém respostas em português;
- funciona corretamente com um ou vários produtos na mesma mensagem.

Métricas futuras podem incluir precisão de roteamento, taxa de respostas sem evidência, taxa de indisponibilidade, latência e avaliação humana das explicações.

## Fases do projeto

## Ordem recomendada para começar

## Primeiro fluxo implementável: FAQ/RAG

O inventário atual mostra que o projeto já possui o agente FAQ/RAG e a ferramenta de busca, mas ainda não possui um grafo orquestrador, estado compartilhado, roteador, compilador ou API FastAPI.

O primeiro fluxo deve conter apenas o caminho de FAQ/RAG. O Product Flow Advisor ficará para a etapa seguinte.

### Decisão sobre roteador e compilador

No MVP, roteador e compilador devem ser tratados como **nodes do LangGraph**, e não como agentes autônomos com ferramentas.

- O **roteador** classifica a intenção e escolhe uma rota estruturada.
- O **agente FAQ/RAG** responde usando a ferramenta `faq_search`.
- O **compilador** transforma o resultado validado em resposta final.

Essa separação evita que o roteador e o compilador criem loops, chamem ferramentas indevidas ou disputem a responsabilidade do agente especializado.

### Fluxo básico

```text
START
  ↓
Preparar turno e sessão
  ↓
Guardrail de entrada
  ├── inválida → resposta controlada → guardrail final → END
  └── válida
        ↓
      Roteador
        ├── faq → Agente FAQ/RAG
        │             ↓
        │       Validador da resposta
        │             ↓
        │         Compilador
        │             ↓
        ├── fora do escopo → resposta controlada
        └── ambígua → pedido de esclarecimento
                      ↓
                Guardrail final
                      ↓
                     END
```

Mesmo quando o resultado vier de um único agente, o fluxo deve passar pelo compilador no primeiro desenho. No início ele poderá apenas normalizar ou repassar a resposta, mas manterá um ponto único para futuras respostas compostas.

### Intenções iniciais do roteador

O roteador deve trabalhar com um conjunto pequeno e fechado:

- `faq`: pergunta respondível pela base documental;
- `fora_do_escopo`: não pertence ao FAQ/RAG nem ao escopo atual;
- `ambigua`: não há informação suficiente para escolher a rota;
- `insegura`: bloqueada pelo guardrail;
- `indisponivel`: rota válida, mas uma dependência necessária não está disponível.

As intenções de produto e fluxo podem ser reservadas no contrato, mas não devem ser encaminhadas para um agente inexistente. Enquanto o Product Flow Advisor não existir, essas perguntas devem resultar em resposta controlada de indisponibilidade ou de funcionalidade ainda não disponível.

### Estado compartilhado inicial

O estado deve representar um turno de conversa, não o trace inteiro. O trace detalhado será produzido por eventos de observabilidade associados ao turno.

#### Sessão e turno

- `session_id`: identifica a conversa;
- `turn_id`: identifica a mensagem atual;
- `user_id`: identificador autorizado do usuário, sem dados desnecessários;
- `user_role`: funcionário, gerente ou gerente regional;
- `user_message`: mensagem recebida;
- `messages`: histórico necessário para o agente, com limite definido;
- `started_at` e `updated_at`.

#### Segurança e controle

- `input_guardrail`: resultado da validação de entrada;
- `route`: intenção e node de destino;
- `route_status`: pendente, encaminhada, concluída ou recusada;
- `output_guardrail`: resultado da validação final;
- `turn_status`: em processamento, concluído, recusado, indisponível ou erro.

#### Respostas e evidências

- `agent_outputs`: resultados por agente e por execução;
- `evidence`: fontes recuperadas pelo FAQ/RAG;
- `validation`: resultado da validação do agente;
- `compiled_response`: resposta consolidada;
- `final_response`: resposta liberada para a API;
- `error`: erro técnico ou de dependência, sem expor detalhes internos ao usuário.

#### Observabilidade

- `trace_id` e `correlation_id`;
- `agent_runs` ou referências para os runs;
- ferramentas chamadas;
- duração;
- modelo e versão do prompt;
- contagem de tokens, quando disponível.

### Ownership do estado

| Campo | Dono da escrita | Leitores principais |
|---|---|---|
| sessão e turno | API/orquestrador | todos os nodes |
| `input_guardrail` | guardrail de entrada | roteador e auditoria |
| `route` | roteador | orquestrador e auditoria |
| `agent_outputs` | agente correspondente | validador e compilador |
| `evidence` | ferramenta/agente RAG | validador e compilador |
| `validation` | validador | compilador e guardrail final |
| `compiled_response` | compilador | guardrail final |
| `final_response` | guardrail final/orquestrador | API |
| eventos de execução | observabilidade | plataforma de análise |

Nenhum agente deve sobrescrever a resposta de outro agente. Se futuramente houver paralelismo, `agent_outputs`, `evidence` e eventos deverão usar merge append-only com identificador de execução.

### Contrato conceitual do resultado do FAQ/RAG

O resultado do agente deve ser tratado como uma resposta com evidência, não apenas como texto. O contrato precisa preservar:

- texto produzido;
- fontes retornadas pela ferramenta;
- indicação de que a ferramenta foi utilizada;
- status de evidência encontrada ou não encontrada;
- eventual recusa por falta de base;
- identificador da execução.

O compilador não deve aceitar uma resposta factual sem evidência quando a pergunta exigir consulta à base. Também não deve transformar a ausência de evidência em uma resposta inventada.

### Responsabilidade de cada node

| Node | Responsabilidade | Não deve fazer |
|---|---|---|
| preparação do turno | criar IDs e carregar contexto permitido | decidir intenção |
| guardrail de entrada | validar segurança e escopo básico | responder conteúdo documental |
| roteador | classificar e encaminhar | consultar RAG para responder |
| FAQ/RAG | consultar `faq_search` e responder | usar conhecimento externo |
| validador | verificar fonte, escopo e formato | reescrever livremente os fatos |
| compilador | organizar o resultado | criar evidências |
| guardrail final | validar exposição e segurança | alterar a regra de negócio |
| finalização | persistir e devolver resultado | executar operação comercial |

### Critérios de aceite do primeiro fluxo

- pergunta documental válida chega ao FAQ/RAG;
- o FAQ/RAG utiliza a ferramenta de busca;
- a resposta preserva a fonte do documento;
- pergunta sem evidência resulta em recusa controlada;
- pergunta insegura não chama o agente;
- pergunta ambígua não chama o FAQ sem esclarecimento;
- pergunta sobre fluxo de produto não é respondida pelo FAQ como se fosse documentação;
- falha da dependência resulta em indisponibilidade controlada;
- a resposta final passa pelo compilador e pelo guardrail final;
- o turno possui `session_id`, `turn_id`, rota e status final.

### Ordem prática deste incremento

1. Fechar e tipar o contrato do estado.
2. Definir as categorias e o contrato de saída do roteador.
3. Definir o contrato de validação e compilação.
4. Montar o grafo somente com a rota FAQ/RAG.
5. Criar testes unitários com modelos e ferramentas falsas.
6. Testar o fluxo com a base RAG existente.
7. Só depois expor o grafo por FastAPI.
8. Adicionar Product Flow Advisor como uma nova branch.

## Estratégia de schemas para o primeiro fluxo sem guardrails

As versões fixadas no projeto são LangChain `1.3.14`, LangGraph `1.2.10` e Pydantic `2.13.4`.

### Recomendação

Usar uma combinação de estruturas, cada uma com uma responsabilidade:

| Estrutura | Uso recomendado | Motivo |
|---|---|---|
| `TypedDict` | estado compartilhado do `StateGraph` | compatível com updates parciais, reducers e o estado de agentes LangChain |
| `BaseModel` | contratos de entrada/saída e saída estruturada do LLM | validação em runtime, enums e limites de formato |
| `dataclass` | contexto de execução e dependências | agrupa serviços, configurações e recursos sem misturar com o estado mutável |
| `Annotated` com reducer | mensagens e listas acumulativas | define como múltiplas escritas serão combinadas |

O estado principal não deve ser um `BaseModel` neste primeiro desenho. Embora o LangGraph aceite Pydantic, a documentação registra limitações: a saída do grafo não retorna automaticamente como instância Pydantic, a validação ocorre principalmente na entrada do primeiro node e a validação recursiva pode ser mais lenta. O `TypedDict` é mais adequado para o estado operacional do grafo.

O `BaseModel` ainda é a melhor escolha para `RouteDecision`, `AgentAnswer` e `CompiledResponse`, pois esses objetos representam contratos estruturados e precisam ser validados antes de entrarem no estado.

### Organização de pastas

Não é recomendável misturar o estado compartilhado com `src/models/`, pois essa pasta já representa os provedores de modelos Gemini (`get_chat_model` e `get_embeddings`). A organização sugerida é:

```text
src/
├── agents/
│   ├── faq/
│   ├── router/
│   └── compiler/
├── context/
│   ├── state.py       # TypedDict do estado do grafo
│   ├── schemas.py     # BaseModels de contratos estruturados
│   └── reducers.py    # reducers nomeados, quando necessários
├── graphs/
│   └── faq_graph.py   # montagem do StateGraph
└── models/
    ├── gemini.py      # provedores LLM e embeddings existentes
    └── __init__.py
```

Se o projeto preferir manter uma pasta chamada `models` para todos os schemas, ela deve ser separada semanticamente em subpastas, como `models/providers/` e `models/contracts/`. Ainda assim, `context/state.py` é mais claro para o estado do grafo.

### Estado inicial sem guardrails

O primeiro `GraphState` deve conter apenas o necessário para o caminho normal:

- `session_id`;
- `turn_id`;
- `messages`, com reducer de mensagens;
- `route`;
- `route_reason`, limitado a uma justificativa curta de classificação;
- `agent_name`;
- `agent_output`;
- `evidence`;
- `compiled_response`;
- `status`;
- `error`;
- `trace_id` ou `correlation_id`.

Não incluir ainda campos de guardrail, decisão de produto, execução comercial ou paralelismo. Campos futuros podem ser adicionados de forma aditiva, sem renomear os campos centrais.

### Reducers no fluxo atual

Como o fluxo inicial será sequencial, a maioria dos campos usará o comportamento padrão de substituição do LangGraph. A exceção principal será `messages`, que precisa acumular as mensagens do turno com o reducer de mensagens do LangGraph.

`evidence` e `agent_events` devem ser listas acumulativas quando começarem a ser produzidos por mais de um node. Se forem escritos por apenas um node no MVP, podem usar substituição simples e depois evoluir para reducer antes de habilitar paralelismo.

### Schemas estruturados

O roteador deve produzir um `RouteDecision` fechado, contendo uma intenção entre as rotas permitidas, por exemplo `faq`, `ambiguous`, `out_of_scope` e `unavailable`.

O compilador deve receber um resultado estruturado do agente, preservar as evidências e produzir um `CompiledResponse`. O texto final deve ser consequência do contrato validado, não um novo raciocínio livre sobre a pergunta.

### Agentes LangChain e estado

O `create_agent` do LangChain v1 aceita estado customizado baseado em `TypedDict`; não devemos passar um `BaseModel` como `state_schema` do agente FAQ. O `BaseModel` pode ser usado dentro do node do roteador ou compilador para obter uma saída estruturada do modelo e então convertê-la para um dicionário compatível com o estado compartilhado.

### Decisão para implementação

Para o fluxo normal, a decisão é:

1. `TypedDict` para o estado público do `StateGraph`.
2. `BaseModel` para decisões e contratos estruturados do roteador e compilador.
3. `AnyMessage` e reducer de mensagens para o histórico conversacional.
4. `dataclass` somente para contexto de runtime, como dependências e configurações.
5. `context/state.py` como fonte do schema do grafo.
6. `context/schemas.py` como fonte dos contratos de entrada e saída.

Essa separação mantém o estado do grafo compatível com LangGraph e LangChain, sem impedir validação rigorosa nas fronteiras importantes.

### Primeiro passo — Fechar o contrato do domínio e dos dados

Esta é a primeira atividade recomendada. Antes de criar o novo agente, o grafo ou a API, deve ser produzido um contrato simples e aprovado para responder:

- o que significa fluxo alto, baixo e normal;
- qual lista corresponde a cada fluxo;
- qual ação é apenas sugerida para cada fluxo;
- quais informações explicam a presença ou ausência de um produto;
- qual é o período da análise vigente;
- como uma análise é identificada;
- como a indisponibilidade é representada;
- quais dados o agente pode consultar;
- quais dados o agente nunca pode alterar.

O resultado dessa etapa deve ser uma especificação funcional do Product Flow Advisor, com exemplos de perguntas e respostas esperadas. Não é necessário definir ainda o prompt final nem a implementação do agente.

### Segundo passo — Fazer o inventário do sistema atual

Depois do contrato de negócio, deve-se mapear o que já existe no agente FAQ/RAG:

- ponto de criação do agente;
- ferramentas disponíveis;
- formato atual de entrada e saída;
- configuração de modelo;
- comportamento de erro;
- testes existentes;
- dependências e pontos que precisam continuar funcionando.

O objetivo é separar o que será preservado do que será reorganizado. A migração para FastAPI não deve começar com uma reescrita do FAQ.

### Terceiro passo — Definir as fronteiras entre ML, integrações e agentes

Deve ser decidido qual integração fornecerá ao sistema:

- catálogo de produtos;
- resultado vigente do ML;
- lista de produtos por fluxo;
- motivo estruturado da elegibilidade ou não elegibilidade;
- metadados da análise;
- status de disponibilidade.

O agente deve receber dados prontos para consulta. Ele não deve calcular frequência, reclassificar produtos ou aplicar uma interpretação própria da confiança do ML.

### Quarto passo — Definir o contrato de saída do Product Flow Advisor

Antes do texto amigável, cada execução deve gerar uma resposta estruturada contendo, conceitualmente:

- intenção atendida;
- produtos encontrados;
- fluxo de cada produto;
- ação sugerida, quando houver;
- motivo estruturado;
- evidências e versão da análise;
- status de disponibilidade;
- indicação de que a resposta pode ser exibida ao usuário.

Esse contrato será utilizado pelo validador, pelo compilador, pelo estado compartilhado e depois pela API.

### Quinto passo — Projetar o estado compartilhado e os eventos

Somente após os contratos de entrada e saída estarem definidos, deve-se fechar:

- campos do estado;
- ownership de cada campo;
- campos append-only;
- reducers para execuções paralelas;
- dados transitórios;
- dados persistidos;
- eventos analíticos;
- correlação entre sessão, turno, execução, agente e ferramenta.

### Sexto passo — Definir a estratégia de validação

Criar a matriz de cenários que deverá ser aceita pelo sistema:

- pergunta de FAQ;
- consulta de fluxo;
- produto em fluxo alto;
- produto em fluxo baixo;
- produto em fluxo normal;
- produto ausente da lista de promoção;
- produto ausente da lista de pedido;
- produto inexistente;
- análise indisponível;
- pergunta ambígua;
- múltiplos produtos;
- tentativa de execução de operação;
- mensagem fora do escopo.

Essa matriz deve ser definida antes da implementação para evitar que a qualidade seja avaliada apenas pela fluidez textual da resposta.

### Sétimo passo — Desenhar o grafo LangGraph

Com os contratos definidos, desenhar os nodes, branches, condições de parada e pontos de fallback:

```text
Entrada
  → Guardrail de entrada
  → Roteador
  → FAQ/RAG ou Product Flow Advisor
  → Validador de saída do agente
  → Compilador, se necessário
  → Guardrail final
  → Resposta
```

O segundo agente futuro não deve entrar no grafo inicial. O grafo inicial deve conter apenas o FAQ/RAG, o Product Flow Advisor, os guardrails necessários, o roteador e o compilador quando houver múltiplas respostas.

### Oitavo passo — Escolher persistência e observabilidade

Com o estado já conhecido, selecionar:

- mecanismo de checkpoint do LangGraph;
- armazenamento de sessões e mensagens;
- armazenamento de eventos analíticos;
- ferramenta de tracing;
- estratégia de retenção de três dias;
- mascaramento de dados.

Não se deve escolher a ferramenta de observabilidade antes de definir quais eventos serão produzidos e quais dados podem ser enviados para ela.

### Nono passo — Planejar a migração para FastAPI

Só então definir os contratos HTTP da primeira versão síncrona:

- criar sessão;
- enviar mensagem;
- consultar histórico autorizado;
- health check;
- readiness check.

Os endpoints de análise profunda devem ser separados e protegidos. Eles não fazem parte da resposta normal do chatbot.

### Décimo passo — Implementar por fatias verticais

A primeira fatia implementável deve atravessar o sistema inteiro com o menor escopo:

```text
Uma mensagem válida
  → sessão
  → guardrail de entrada
  → roteamento para FAQ/RAG
  → validação
  → guardrail final
  → resposta síncrona
```

Depois, adicionar o Product Flow Advisor com uma única consulta de fluxo. Em seguida, adicionar explicações de ausência em pedido/promoção, múltiplas intenções, persistência analítica e demais recursos.

Essa ordem reduz o risco porque preserva o agente já existente, valida a API antes do paralelismo e só adiciona complexidade depois que os contratos básicos estiverem funcionando.

## Gate para sair do planejamento e iniciar implementação

A implementação só deve começar quando estes itens estiverem aprovados:

- contrato dos três fluxos;
- contrato da listagem por fluxo;
- contrato dos motivos estruturados;
- contrato de disponibilidade e indisponibilidade;
- contrato de entrada e saída do Product Flow Advisor;
- matriz de permissões dos perfis;
- matriz de cenários de aceitação;
- desenho inicial do estado compartilhado;
- política de retenção e dados sensíveis;
- decisão provisória sobre persistência e observabilidade.

### Fase 1 — Contratos de negócio

Documentar os três fluxos, listas, origem dos dados e comportamento de indisponibilidade.

### Fase 2 — Contratos de dados

Definir catálogo, resultado do ML, análise, listagens, motivos e versões.

### Fase 3 — Estado e persistência

Definir ownership, reducers, checkpoint, eventos, retenção e privacidade.

### Fase 4 — Isolamento do FAQ/RAG

Preservar as regras atuais e definir seu contrato com o grafo.

### Fase 5 — Product Flow Advisor

Criar as consultas estruturadas e os fluxos de explicação, sem executar operações.

### Fase 6 — Guardrails e compilador

Separar validação dos agentes, compilação e validação final.

### Fase 7 — Observabilidade

Escolher a ferramenta, padronizar IDs de correlação e construir a timeline de sessão.

### Fase 8 — API FastAPI

Expor sessões, mensagens, histórico e health checks.

### Fase 9 — Testes de aceitação

Validar rotas, respostas com evidências, indisponibilidade, permissões e retenção.

### Fase 10 — Agente futuro de operações

Somente após a definição de autorização, confirmação e execução de pedidos ou promoções.

## Questões ainda abertas

- Qual é o formato real das tabelas produzidas pelo ML?
- Quais identificadores ligam produto, venda e compra?
- O ML publicará confiança, score ou apenas o fluxo?
- A lista por fluxo terá uma versão imutável por período?
- Como a API receberá a indisponibilidade do pipeline de dados?
- Qual será o banco ou serviço de persistência?
- Qual será a política de autenticação dos três perfis?
- Quais dados do usuário serão considerados sensíveis?
- Os gerentes poderão visualizar dados diferentes dos funcionários?
- Qual solução de observabilidade será aprovada?
- O app precisará de uma consulta estruturada de recomendações separada do chat?

## Regra de manutenção deste planejamento

Este documento é a referência principal do planejamento. Novas decisões de negócio, arquitetura, persistência, observabilidade ou escopo devem ser adicionadas aqui antes da implementação correspondente.

Enquanto o projeto não possuir uma memória compartilhada entre sessões, novas conversas devem consultar este arquivo para retomar o contexto.

## Referências técnicas consultadas

- [LangSmith Observability](https://docs.langchain.com/langsmith/observability): tracing, investigação de runs, dashboards, alertas e avaliações para aplicações LLM.
- [OpenTelemetry — Observability primer](https://opentelemetry.io/docs/concepts/observability-primer/): conceitos de traces, métricas, logs, correlação e instrumentação.
- [Grafana Tempo](https://grafana.com/docs/tempo/latest/): backend de tracing distribuído e integração com métricas e logs.
- [Grafana Loki](https://grafana.com/docs/loki/latest/get-started/): agregação de logs.
- [Prometheus no Grafana](https://grafana.com/docs/grafana/latest/datasources/prometheus/): métricas, consultas e alertas.




