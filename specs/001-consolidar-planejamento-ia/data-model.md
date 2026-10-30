# Data Model: Inventário de planejamento

Este modelo descreve registros documentais da auditoria. Não é um schema de
produção nem deve ser persistido no PostgreSQL, MongoDB, Redis ou Qdrant.

## PlanningItem

Representa qualquer decisão, requisito, regra, capacidade ou restrição incluída
na auditoria.

| Campo | Obrigatório | Descrição |
|---|---:|---|
| `item_id` | Sim | Identificador estável, por exemplo `AUD-001` ou um requisito `FR-001`. |
| `title` | Sim | Nome curto e inequívoco do item. |
| `kind` | Sim | `decision`, `requirement`, `rule`, `capability`, `constraint` ou `gap`. |
| `status` | Sim | Exatamente um de `confirmado`, `implementado`, `proposto`, `aberto` ou `divergente`. |
| `current_state` | Sim | O que existe hoje, com linguagem observável. |
| `target_state` | Não | O comportamento ou decisão pretendida. |
| `source_refs` | Sim | Caminhos e seções que originaram o item. |
| `evidence_refs` | Não | Código, teste, documento, execução ou demonstração que sustenta a classificação. |
| `impact` | Sim | Escopo, arquitetura, dados, segurança, operação ou evidência acadêmica afetados. |
| `open_decision` | Não | Decisão necessária quando o item estiver `aberto` ou `divergente`. |
| `feature_ref` | Não | Diretório Spec Kit responsável pela evolução do item. |

## Decision

Representa uma escolha aprovada, proposta ou pendente que altera o
planejamento.

| Campo | Obrigatório | Descrição |
|---|---:|---|
| `decision_id` | Sim | Identificador estável, por exemplo `DEC-001`. |
| `question` | Sim | Pergunta que precisava ser decidida. |
| `answer` | Sim quando decidida | Resposta escolhida ou `pendente`. |
| `status` | Sim | Status da decisão segundo a taxonomia do projeto. |
| `rationale` | Sim | Motivo e impacto da escolha. |
| `alternatives` | Não | Alternativas consideradas e rejeitadas. |
| `recorded_in` | Sim | Caminho do artefato Spec Kit que registra a decisão. |

## Evidence

Representa uma fonte verificável do estado atual ou de uma conclusão de
auditoria.

| Campo | Obrigatório | Descrição |
|---|---:|---|
| `evidence_id` | Sim | Identificador estável, por exemplo `EVD-001`. |
| `type` | Sim | `source`, `test`, `code`, `document`, `execution` ou `demo`. |
| `location` | Sim | Caminho absoluto na coleta e referência relativa no documento. |
| `claim` | Sim | O que a evidência sustenta. |
| `scope` | Sim | Repositório, módulo, serviço ou fluxo coberto. |
| `observed_at` | Não | Data da observação ou execução. |
| `limitations` | Não | O que a evidência não prova. |

## FeatureRecord

Representa uma funcionalidade planejada sob `specs/`.

| Campo | Obrigatório | Descrição |
|---|---:|---|
| `feature_id` | Sim | Diretório numerado, por exemplo `001-consolidar-planejamento-ia`. |
| `name` | Sim | Nome da funcionalidade. |
| `spec_path` | Sim | Caminho de `spec.md`. |
| `plan_path` | Não | Caminho de `plan.md` após o planejamento. |
| `tasks_path` | Não | Caminho de `tasks.md` após a decomposição. |
| `status` | Sim | Estado do ciclo: `draft`, `clarified`, `planned`, `tasked`, `implemented` ou `verified`. |
| `scope` | Sim | O que a funcionalidade inclui e exclui. |

## TraceabilityLink

Liga um item de planejamento a uma decisão, tarefa, código, teste ou evidência.

| Campo | Obrigatório | Descrição |
|---|---:|---|
| `link_id` | Sim | Identificador estável, por exemplo `TRC-001`. |
| `from_id` | Sim | Item de origem. |
| `relation` | Sim | `decides`, `satisfies`, `implements`, `tests`, `evidences`, `conflicts` ou `depends_on`. |
| `to_id` | Sim | Item de destino. |
| `note` | Não | Contexto da relação ou limitação. |

## Regras de integridade

- Cada `PlanningItem` deve possuir pelo menos uma referência de origem.
- `divergente` exige duas ou mais evidências ou fontes conflitantes e uma
  decisão necessária.
- `aberto` não pode ser ligado a uma tarefa executável se a decisão pendente
  alterar substancialmente a solução.
- `implementado` exige evidência de código, teste ou execução; uma descrição
  documental isolada não basta.
- Uma decisão `confirmado` pode ter implementação pendente, desde que isso
  apareça explicitamente em `current_state` ou `evidence_refs`.
- Nenhum item deve apontar para segredos, credenciais, caches ou ambientes
  virtuais como evidência do produto.
