# Revisão da observabilidade na branch `refactor`

Revisão de código em 13/10/2026. Base de requisitos: `Quistock/docs/sdd/academic-constraints.md` e `Quistock/docs/sdd/specs/observabilidade-e-laboratorio-de-agentes.md`. Os testes de cálculo verificam dados sintéticos; não substituem uma medição de carga ou conferência de faturamento real.

## O que os números significam

| Indicador | Cálculo implementado | Avaliação |
| --- | --- | --- |
| Erro de traces | `error / todos os traces do filtro` | Correto para traces finais persistidos; é falha técnica, não resposta inadequada. |
| Conclusão técnica | `completed / (completed + error)` em 28 dias | Alinhado ao SLI do piloto. Rejeição controlada, pedido de esclarecimento e fora de escopo podem ser `completed`. |
| Latência | Duração no servidor; p95 pelo posto `ceil(0,95 × N)` | Cálculo correto. O SLO exige 95% dos turnos em até 20 s; ausência de duração conta como falha no SLO. Não inclui rede/navegador. |
| Chamadas LLM por modelo | `completed / (completed + error)` dos spans LLM terminais | Correto para chamadas capturadas pelos callbacks. Chamadas fora desse mecanismo não aparecem. |
| Orçamento de erro | `(falhas / total) / (1 - meta) × 100` | Cálculo correto; restante é limitado a zero. Metas provisórias: 99,5% dos turnos, 95% em até 20 s e 99% das chamadas por modelo. |
| Tokens e custo LLM | `entrada × tarifa_entrada / 10⁶ + saída × tarifa_saída / 10⁶` | Não substitui uso ou tarifa ausente por zero. Só há preço configurado para ID exato `gpt-6-luna`. O custo por turno divide o custo dos traces concluídos pelo número de traces concluídos; não mede custo por resolução de negócio. |
| Custo por origem | Spans LLM do turno + eventos `ai_usage` de laboratório, resumo, título e embeddings | Evita duplicar `agent_turn`; resultado incompleto vira `null` quando há chamada não precificada. O marco de início da medição não garante que todos os eventos posteriores foram gravados. |
| Fallback | Exige `fallback_used` booleano em todos os traces | Indicador sem sinal de produção: o fluxo não escreve esse campo e a sanitização do repositório não o preserva. A busca de memória deixou de usar fallback recente. |

Implementação principal: `src/observability/metrics.py`, `src/api/services/observability_service.py`, `src/observability/traces.py` e `src/observability/ai_usage_repository.py`.

## Lacunas e decisões

1. **Cobertura de custo e modelo:** o juiz JEV chama a TypeSafe diretamente e retorna contagens de tokens, mas não gera span LLM nem evento `ai_usage`. Ele fica fora da taxa de chamadas por modelo e do custo total. É necessário registrar uma origem própria, uma tarifa verificável e o estado da chamada antes de chamar o agregado de custo de aplicação de completo. A tarifa atual do GPT-6 Luna corresponde ao preço padrão de contexto curto sem cache; outros modos, cache e contexto longo podem ter tarifas diferentes. O preço de texto do Gemini Embedding 2 pago é US$ 0,20 por milhão de tokens, enquanto o tier gratuito é condicionado à cota da conta. Fontes: [OpenAI](https://developers.openai.com/api/docs/pricing) e [Google](https://ai.google.dev/gemini-api/docs/pricing).
2. **Perda de telemetria:** falhas ao salvar trace ou evento de uso são registradas em log e não interrompem a resposta, como desejado. Falta fila/retry para recuperação, exigida pela proposta `RNF-OBS-007`. A tela pode exibir cobertura completa após o início da medição mesmo com eventos perdidos.
3. **Fallback:** remover o indicador até existir uma definição de fallback relevante e instrumentação explícita, ou implementá-lo de ponta a ponta. Hoje seus testes alimentam `fallback_used` manualmente, sem reproduzir o pipeline real.
4. **Entrega acadêmica:** a rubrica pede cenários de 100 e 1.000 usuários semanais, latência, erro, ROI e custo por resolução. A API oferece os dados técnicos básicos e custo de IA estimado. Não implementa projeção/carga dos dois cenários, custo por resolução de negócio ou ROI realizado. A própria especificação registra falta de execução comercial verificada, margem e linha de base; esses resultados dependem de dados e decisões adicionais.
5. **Escopo do protótipo:** as rotas de métricas, traces, conversas, prompt do agente e laboratório são públicas por decisão explícita de 08/10/2026. Antes de produção, é necessário definir autorização e auditoria de acesso. O feed ao vivo é limitado e local a cada processo; a retenção de traces/logs ainda não tem prazo definido.
6. **Consultas de métricas:** cada requisição varre traces para o filtro, traces globais para custo e traces de 28 dias para SLO. O desempenho com 4.000 e 40.000 turnos por 28 dias não foi medido. Essa validação deve preceder qualquer afirmação de capacidade para 100/1.000 usuários.

Os três SLIs e os respectivos SLOs, traces seguros e custo por origem servem ao piloto. A taxa de fallback sem sinal, os detalhes extensos do laboratório e comparações de experimentos não são necessários para satisfazer a rubrica acadêmica básica. Alguns deles pertencem à visão proposta da plataforma, não às decisões fechadas para o protótipo.
