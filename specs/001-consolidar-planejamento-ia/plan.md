# Implementation Plan: Consolidar o planejamento do serviço de IA

**Branch**: `001-consolidar-planejamento-ia` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-consolidar-planejamento-ia/spec.md`

## Summary

Esta feature consolida o planejamento do serviço de IA do Quistock em artefatos
versionados pelo Spec Kit. O trabalho produzirá uma auditoria rastreável dos
dois repositórios, separará estado implementado de arquitetura-alvo e roadmap,
classificará cada item com os cinco status acordados e registrará divergências
sem resolvê-las silenciosamente.

O resultado é documental e de governança. Ele não altera o código da aplicação,
não cria uma API nova e não substitui capacidades implementadas. Capacidades
existentes serão documentadas com evidências; especificações retrospectivas
completas serão criadas somente quando forem relevantes para a rubrica
acadêmica. Mudanças e funcionalidades futuras serão planejadas em diretórios
independentes sob `specs/`. O resultado principal da auditoria será o
`audit-inventory.md`, validado pelo contrato documental correspondente.

## Technical Context

**Language/Version**: Markdown para os artefatos de planejamento; Python `>=3.14` é a versão declarada do repositório `AI_Multi-Agent` e será apenas contexto para identificar evidências executáveis.

**Primary Dependencies**: Git, Spec Kit, PowerShell, `rg`, Markdown e os testes existentes do serviço de IA.

**Storage**: Arquivos versionados sob `AI_Multi-Agent/specs/`; não haverá banco de dados ou persistência de runtime para esta feature.

**Testing**: Validação estrutural dos artefatos, checklist de requisitos, análise de rastreabilidade e execução seletiva dos testes existentes quando uma evidência precisar ser confirmada.

**Target Platform**: Repositórios locais `AI_Multi-Agent` e `Quistock`, com revisão realizada no ambiente de desenvolvimento da equipe.

**Project Type**: Processo de especificação e auditoria documental para um serviço web multiagente existente.

**Performance Goals**: A auditoria deve cobrir todos os artefatos relevantes dos dois repositórios e produzir uma classificação verificável para cada item incluído, sem exigir uma meta de latência de runtime.

**Constraints**: Não alterar código de aplicação, contratos executáveis ou comportamento em produção; excluir caches, ambientes virtuais, artefatos gerados e segredos; preservar documentos históricos como contexto; usar `AI_Multi-Agent/specs` como fonte oficial das decisões ativas.

**Scale/Scope**: Dois repositórios; código, testes, documentação, configurações e contratos que influenciem comportamento, segurança, dados, operação ou evidências acadêmicas do serviço de IA.

## Constitution Check

*GATE: Must pass before Phase 0 research and re-check after Phase 1 design.*

| Principle | Status | Evidence / Application |
|---|---|---|
| I. Spec-First and Traceable Delivery | PASS | A especificação ativa existe em `specs/001-consolidar-planejamento-ia`; este plano e seus artefatos serão mantidos no mesmo diretório. |
| II. Explicit Status and No Silent Decisions | PASS | A auditoria usa exatamente `confirmado`, `implementado`, `proposto`, `aberto` e `divergente`; conflitos permanecem explícitos. |
| III. Contracts and Bounded Responsibilities | PASS | O plano não cria capacidades de runtime; o contrato produzido descreve somente o formato da auditoria e da rastreabilidade. |
| IV. Evidence-Grounded and Fail-Safe AI | PASS | Código, testes e documentos serão tratados como evidências separadas; nenhuma conclusão de comportamento será inventada. |
| V. Identity, Privacy and Tenant Isolation | PASS | Segredos e dados sensíveis ficam fora do inventário; a auditoria não expõe credenciais nem altera dados comerciais. |
| VI. Tests, Review and Academic Evidence | PASS | O checklist, os critérios de aceite e o quickstart formam a evidência verificável da feature documental. |

## Phase 0: Research and Decisions

As decisões abaixo foram derivadas da especificação, da constituição e das
respostas registradas na sessão de `clarify`. Não há dependência de pesquisa
externa para esta feature.

- Definir `AI_Multi-Agent/specs` como fonte oficial das decisões ativas.
- Manter `Quistock/docs/sdd` como contexto histórico e preservar referências
  relevantes.
- Auditar os dois repositórios, incluindo relações e contratos entre eles.
- Separar o status da decisão do status da implementação.
- Classificar conflito entre código e testes como `divergente`, preservando as
  duas evidências.
- Registrar capacidades implementadas na auditoria; criar especificação
  retrospectiva completa somente quando houver relevância acadêmica.
- Criar especificações completas para mudanças e funcionalidades futuras.

Os detalhes, alternativas e consequências estão em [research.md](./research.md).

## Phase 1: Design and Contracts

### Data model

O modelo documental da auditoria está em [data-model.md](./data-model.md). Ele
define itens de planejamento, decisões, evidências, funcionalidades e links de
rastreabilidade sem introduzir uma estrutura de banco de dados.

### Contracts

O formato mínimo do inventário e dos links está em
[contracts/audit-inventory.md](./contracts/audit-inventory.md). Esse contrato é
documental e não representa um endpoint de produção.

### Audit inventory

O inventário preenchido da primeira auditoria será mantido em
[audit-inventory.md](./audit-inventory.md), usando o contrato documental e as
regras de classificação definidos nesta feature.

### Validation guide

Os cenários de verificação, comandos permitidos e critérios esperados estão em
[quickstart.md](./quickstart.md).

## Project Structure

### Documentation (this feature)

```text
specs/001-consolidar-planejamento-ia/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── audit-inventory.md
├── contracts/
│   └── audit-inventory.md
└── checklists/
    └── requirements.md
```

### Source Code (repositories under audit)

```text
AI_Multi-Agent/
├── src/                         # serviço FastAPI, agentes, grafo e memória
├── tests/                       # evidências automatizadas
├── docs/                        # planejamento e contexto do serviço
├── .specify/                    # governança e templates Spec Kit
└── specs/                       # especificações oficiais do serviço

Quistock/
├── docs/sdd/                    # contexto de negócio, acadêmico e decisões históricas
├── ai-service/                  # snapshot adicional do serviço de IA
└── scripts e modelos de dados   # contratos e evidências interdisciplinares
```

**Structure Decision**: A documentação de cada funcionalidade permanece em seu
próprio diretório sob `AI_Multi-Agent/specs`. Os dois repositórios continuam
separados para preservar seu histórico, enquanto a auditoria registra as
relações e a fonte de cada evidência.

## Pre-Implementation Exit Gate

Antes de iniciar a implementação desta feature, a equipe deve confirmar que:

- o inventário cobre os dois repositórios e exclui artefatos fora de escopo;
- cada item tem uma das cinco classificações;
- divergências identificam fontes, impacto e decisão necessária;
- decisões ativas estão registradas em artefatos do Spec Kit;
- capacidades existentes têm evidências suficientes ou estão marcadas como
  lacunas;
- mudanças futuras podem ser decompostas em especificações independentes.

## Complexity Tracking

Não há violação da constituição que exija justificativa. A criação de um
contrato documental e de um modelo de auditoria é necessária para cumprir a
rastreabilidade e não introduz uma camada de runtime.
