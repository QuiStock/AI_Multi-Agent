# Implementation Plan: Product Workflow

**Branch**: `product_workflow` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Adicionar a rota `product_workflow` ao serviço multiagente para explicar o snapshot de card recebido sem consultar o banco quando a pergunta for sobre aquele produto. Para outro produto ou pergunta sem card, uma tool tipada executará consulta PostgreSQL predefinida e somente leitura, respeitando cargo, loja e sugestões sem evento `EXPIRED`. Quando o nome identificar vários produtos, o fluxo deve apresentar opções distinguíveis e aguardar a escolha do usuário antes de responder.

**Decisão sobre seleção**: não criar uma tool separada para escolher nem persistir um estado especial de seleção. O agente apresenta somente os dados necessários para distinguir os resultados; o usuário escolhe na mensagem seguinte. O workflow usa o contexto normal da conversa para entender a escolha e consulta novamente a tool dentro do escopo autenticado antes de responder. Se não conseguir determinar a escolha pelo contexto disponível, pede ao usuário que identifique o produto novamente. Ver [research.md](research.md#decisão-r-004--seleção-de-opções-ambíguas).

## Technical Context

**Language/Version**: Python conforme `pyproject.toml`; versão exata definida pelo ambiente/lockfile do repositório.  
**Primary Dependencies**: FastAPI, Pydantic, LangChain e LangGraph (versões resolvidas em `uv.lock`; atualmente LangChain 1.3.14 e LangGraph 1.2.10).  
**Storage**: pool PostgreSQL `psycopg_pool` existente, com SELECT somente nas tabelas mínimas da consulta comercial; MongoDB para histórico, sem persistência dedicada à desambiguação; Redis/Qdrant fora do caminho principal desta feature.  
**Testing**: pytest (unitário, contrato e integração), Ruff e mypy conforme `AGENTS.md`.  
**Target Platform**: Serviço HTTP FastAPI executado em ambiente local/servidor.  
**Project Type**: Backend Python multiagente.  
**Performance Goals**: Sem metas numéricas novas na spec; consulta limitada, timeout definido e sem chamadas SQL para pergunta sobre o snapshot correspondente.  
**Constraints**: SQL parametrizado e fixo; conexão read-only existente; escopo de loja derivado no servidor; email e role vêm da autenticação JWE, enquanto role deve ser propagado ao GraphState; dados do snapshot tratados como evidência de origem cliente; nenhuma operação comercial de escrita. Mapeamento inicial revisado contra `Quistock/quistock-updated.sql`; validar que o ambiente usa essa mesma versão antes de implementar. Ampliar documentação dos grants mínimos além de `user_account`.  
**Scale/Scope**: Um novo AgentCard, executor e tool de busca de card; integração com schemas HTTP/GraphState, router, compiler, judge e testes correspondentes.

## Constitution Check

- **I. Spec-first**: conforme; esta feature tem diretório Spec Kit próprio e sequência `spec → clarify → plan → tasks → analyze → implementação → testes → evidências`.
- **II. Status explícito**: conforme; regras da spec são decisões confirmadas; a regra de seleção simplificada foi confirmada; a fonte exata de qualquer atributo adicional para distinguir produtos permanece `aberto` e não deve virar tarefa assumindo uma coluna inexistente.
- **III. Contratos e limites**: conforme; agente consultivo e tool restrita, tipada, somente leitura; sem SQL livre ou escrita comercial.
- **IV. Evidência e segurança**: conforme; juiz recebe evidência de origem declarada; ausência/erro de dados não pode ser preenchida por inferência.
- **V. Identidade e isolamento**: conforme com condição; email/role vêm do principal autenticado; loja é derivada por vínculo ativo no servidor. A resolução de ambiguidade sempre reconsulta usando o mesmo contexto autorizado.
- **VI. Testes e evidências**: conforme; tarefas devem cobrir roteamento, isolamento, groundedness, seleção ambígua e falhas dependentes.

**Recheck após design**: sem violações identificadas. A escolha ocorre por mensagem normal e contexto da conversa, sem ferramenta ou persistência especial. O SQL fornecido não tem campo de apresentação; a tool usa somente os atributos disponíveis necessários para distinguir opções. A ampliação read-only dos grants deve ser registrada no ADR de autenticação e comprovada no ambiente.

## Project Structure

```text
src/
├── api/schemas/                  # snapshot opcional do card na requisição
├── agents/product_workflow/      # AgentCard, executor, prompt e tool(s)
├── agents/schemas/               # schemas reutilizáveis de card/tool result
├── graphs/                       # estado, adapters, decisões e composição
├── api/dependencies.py           # wiring do executor e serviços
└── memory/                       # persistência/recuperação de conversa se necessária
tests/
├── test_product_workflow_*.py    # unitários, contrato e integração do agente/tool
├── test_agent_graph.py           # fluxo, ambiguidade, juiz e saída terminal
└── integration/                  # PostgreSQL fake/temporário e API quando viável
specs/004-product-workflow/       # especificação e artefatos exclusivos da feature
```

**Structure Decision**: manter camadas existentes em `src/` e `tests/`; contratos e decisões pertencentes à feature permanecem em `specs/004-product-workflow/`. Não criar serviço ou projeto separado.

## Complexity Tracking

Sem violações da constituição que exijam justificativa.
