# Quickstart: Validar a consolidação do planejamento

Este guia valida os artefatos da feature sem alterar o código de aplicação.
Execute os comandos a partir da raiz de `AI_Multi-Agent`.

## 1. Confirmar a feature ativa

```powershell
Set-Location "C:\Users\enzojoaquim-ieg\OneDrive - Instituto J&F\Área de Trabalho\Diciplinas Tech\IA\IA-interdisciplinar\AI_Multi-Agent"
& ".specify/scripts/powershell/check-prerequisites.ps1" -Json -PathsOnly
```

Resultado esperado: `FEATURE_SPEC`, `IMPL_PLAN` e `FEATURE_DIR` apontam para
`specs/001-consolidar-planejamento-ia`.

## 2. Validar a estrutura Spec Kit

```powershell
Test-Path "specs/001-consolidar-planejamento-ia/spec.md"
Test-Path "specs/001-consolidar-planejamento-ia/plan.md"
Test-Path "specs/001-consolidar-planejamento-ia/research.md"
Test-Path "specs/001-consolidar-planejamento-ia/data-model.md"
Test-Path "specs/001-consolidar-planejamento-ia/quickstart.md"
Test-Path "specs/001-consolidar-planejamento-ia/contracts/audit-inventory.md"
```

Todos os resultados devem ser `True` antes da geração de `tasks.md`.

## 3. Validar decisões e rastreabilidade

```powershell
rg -n "confirmado|implementado|proposto|aberto|divergente" `
  "specs/001-consolidar-planejamento-ia"
rg -n "FR-[0-9]+|SC-[0-9]+|Q:" `
  "specs/001-consolidar-planejamento-ia/spec.md"
```

Verifique manualmente que:

- cada decisão do `research.md` possui uma origem ou resposta registrada;
- cada item aberto ou divergente possui próxima ação;
- nenhuma tarefa executável foi criada antes da conclusão de `tasks.md`;
- os documentos históricos são referências, não decisões ativas isoladas;
- nenhum segredo, cache ou ambiente virtual aparece como evidência.

## 4. Validar o checklist da especificação

```powershell
Select-String -LiteralPath `
  "specs/001-consolidar-planejamento-ia/checklists/requirements.md" `
  -Pattern "^- \[[xX ]\]"
```

Resultado esperado: todos os itens do checklist permanecem marcados como
aprovados.

## 5. Critérios de aceite da feature

Considere a feature pronta para geração de tarefas somente quando:

1. Os dois repositórios tiverem sido auditados dentro do escopo definido.
2. Cada item incluído tiver exatamente um dos cinco status acordados.
3. Cada divergência preservar suas fontes e sua decisão pendente.
4. Capacidades implementadas tiverem evidências, sem serem confundidas com
   decisões futuras.
5. Decisões ativas estiverem nos artefatos do Spec Kit.
6. Cada mudança futura puder virar uma especificação independente.

Esta feature não exige execução da suíte completa do serviço porque não altera
runtime. Testes de aplicação serão executados quando as tarefas de cada
funcionalidade futura forem implementadas.
