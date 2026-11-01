# Revisão da observabilidade

Revisão do código em 01/11/2026. Os testes de cálculo usam dados sintéticos; não substituem a conferência do consumo real no console TypeSafe nem testes de carga.

## Definições aplicadas

| Indicador | Cálculo | Observação |
| --- | --- | --- |
| Erro de traces | `traces com status error / todos os traces` | Mede falha técnica. Respostas `rejected`, `clarification_required` e `out_of_scope` podem terminar sem erro técnico. |
| Conclusão técnica | `completed / (completed + error)` no período selecionado | Segue os filtros de período, usuário, conversa e ambiente; ignora status para não enviesar o resultado. Não significa que o pedido foi resolvido. |
| Latência | Duração do servidor; p95 pelo posto `ceil(0,95 × N)` | Não inclui rede/navegador. Duração ausente conta como falha no SLO. |
| Chamadas por modelo | Spans LLM; traces antigos também podem usar eventos JEV correlacionados | Cada chamada do JEV agora é registrada como span filho do nó judge e é persistida junto ao trace do turno. |
| Custo JEV | `input_tokens × US$ 0,042 / 1.000.000`; saída US$ 0 | A tarifa é vinculada à origem `judge_jev`, mesmo quando a API devolve uma versão concreta diferente do alias configurado. Usa os tokens devolvidos pela API; se o uso estiver ausente, a estimativa fica incompleta. [Preço oficial TypeSafe](https://typesafe.ai/) · [Resposta e campo de uso da API](https://api.typesafe.ai/redoc). |
| Turnos sem erro | Todo trace persistido com status `completed` | Inclui fora de escopo, rejeição controlada e esclarecimento, conforme definição operacional acordada. A métrica não afirma resolução do problema do usuário. |
| Custo por resolução | Custo variável conversacional do período / turnos sem erro | Inclui custos de turnos com erro no numerador, pois também consumiram IA; o denominador considera só traces sem erro. Esse é o único card de custo por turno. |
| Custo por conversa | Custo variável da janela de referência / conversas observadas na mesma janela | O valor é apresentado e é a base direta das projeções. |
| Projeção semanal | Custo médio por conversa na janela móvel de até 30 dias × `5 × usuários` | 100 usuários = 500 conversas/semana; 1.000 usuários = 5.000. Inclui turnos, JEV e eventos variáveis associados à conversa. A janela não segue o filtro de período da tela; inicia na cobertura de telemetria quando ela tem menos de 30 dias. |
| Laboratório e indexação | Custos separados por origem | Ficam no custo total do período e no ROI; não são extrapolados por usuário/conversa. Eventos operacionais sem conversa associada também ficam separados. |
| ROI do período | `(retorno informado − custo total de IA) / custo total de IA × 100` | O input de retorno deve corresponder ao período selecionado. O resultado líquido também é exibido. “Últimos 7 dias” dá o ROI semanal. |
| Custo incompleto por origem | Chamadas sem uso, sem preço ou sem ambos | As causas são exibidas separadamente; um total incompleto não é convertido em zero. |
| Fallback | Chamadas com `qwen` no model ID de um span LLM | Mostra quantidade de chamadas, turnos com ao menos uma chamada Qwen e proporção sobre traces do período. |

## Modelos observados

O `llm_factory.py` deste checkout usa OpenAI para chat e `gemini-embedding-2` para embeddings. `gemini-3.6-flash` e `qwen/qwen3.8-27b` aparecem em `config.py` como configurações legadas e não são usadas pelo factory atual. A tabela de modelos mostra os IDs encontrados nos traces, então registros do Gemini Flash podem vir de uma implantação anterior ou de outra origem de spans. A métrica Qwen também só consegue contar chamadas que efetivamente chegaram aos traces; zero não comprova que uma implantação externa não chamou Qwen.

## Lacunas restantes

1. Falhas ao persistir traces ou eventos de uso ainda só são registradas em log; não há fila/retry de recuperação. A cobertura iniciada não garante que todos os eventos posteriores tenham sido gravados.
2. O feed ao vivo é local ao processo, e o checkpointer do grafo continua sendo `MemorySaver`; reinícios ou múltiplas instâncias podem perder esses estados.
3. Uma resposta TypeSafe sem tokens observáveis é contabilizada como chamada sem preço/uso suficiente; o custo total e projeções que dependem desse uso ficam incompletos.
4. A instrumentação Qwen mede spans presentes. O fallback Qwen não está configurado pelo factory deste checkout; a versão implantada no Render precisa corresponder ao código antes de interpretar a contagem como telemetria completa.

Implementação principal: `src/observability/metrics.py`, `src/api/services/observability_service.py`, `src/agents/judge/jev_client.py`, `src/observability/usage/ai_usage_repository.py` e `src/observability/front-observer/src/main.js`.
