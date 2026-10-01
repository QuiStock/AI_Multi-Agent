# Contract: Inventário de auditoria

Este contrato define o formato mínimo para registrar os resultados da revisão
dos repositórios. Ele é documental e deve ser usado pelos artefatos de
auditoria, não por uma API de produção.

## Registro mínimo

Cada linha ou seção de inventário deve conter:

| Campo | Regra |
|---|---|
| `item_id` | Único dentro da auditoria e estável após a criação. |
| `title` | Descreve uma única decisão, requisito, capacidade, regra ou lacuna. |
| `status` | Um único valor: `confirmado`, `implementado`, `proposto`, `aberto` ou `divergente`. |
| `current_state` | Descreve o que foi observado nos repositórios. |
| `target_state` | Descreve o estado desejado quando existir. |
| `source_refs` | Lista caminhos relativos e seções de origem. |
| `evidence_refs` | Lista evidências verificáveis ou explica sua ausência. |
| `impact` | Registra áreas afetadas. |
| `next_action` | Decisão, especificação, teste ou revisão necessária. |

## Regras por status

### `confirmado`

Usar quando a decisão ou regra estiver aprovada, mesmo que ainda não esteja
implementada. O registro deve indicar a lacuna de implementação quando houver.

### `implementado`

Usar somente quando houver evidência de comportamento existente. A evidência
deve apontar para código, teste, execução ou demonstração verificável.

### `proposto`

Usar para recomendação técnica ou de escopo ainda não aprovada. Não deve ser
tratado como obrigação de implementação.

### `aberto`

Usar quando falta uma resposta que pode alterar escopo, arquitetura, contrato,
segurança, dados ou validação. Não gerar tarefa executável para esse item.

### `divergente`

Usar quando duas fontes conflitarem, inclusive código contra testes. Preservar
as fontes, registrar o impacto e indicar a decisão necessária.

## Exemplo

```markdown
| ID | Item | Status | Estado atual | Estado-alvo | Fontes | Evidências | Próxima ação |
|---|---|---|---|---|---|---|---|
| AUD-001 | Autenticação da API de IA | confirmado | O endpoint recebe `user_id` no payload; token ainda não é validado. | Identidade e escopo derivados de token validado. | `AGENTS.md`, `docs/...` | `src/api/...`, testes relacionados | Criar especificação de autenticação. |
```

O exemplo é ilustrativo; valores concretos devem ser confirmados durante a
auditoria e ligados a referências existentes.
