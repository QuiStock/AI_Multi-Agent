# Feature Specification: FAQ por audiência de usuário

## Objetivo

Permitir que o agente FAQ recupere somente documentos compatíveis com o
`role_id` autenticado já presente no `GraphState`.

## Regras

- `role_id=2` representa `manager`.
- `role_id=3` representa `employee`.
- `manager` pode consultar `shared` e `manager`.
- `employee` pode consultar `shared` e `employee`.
- Role ausente ou desconhecido falha fechado.
- O modelo recebe somente o argumento `query`; audiência e filtros são
  determinados pelo servidor.
- A autenticação e o contrato do `GraphState` não são alterados.

## Indexação

As fontes devem estar em:

```text
src/data/docs/shared/
src/data/docs/manager/
src/data/docs/employee/
```

Cada chunk indexado deve possuir `audience` no payload do Qdrant. Arquivos fora
desses diretórios não podem ser indexados.

## Critérios de aceite

1. Funcionário não recupera conteúdo exclusivo de gerente.
2. Gerente não recupera conteúdo exclusivo de funcionário.
3. Ambos recuperam conteúdo compartilhado.
4. Pontos sem `audience` não são retornados.
5. O filtro é aplicado antes da resposta do agente.
6. Chamadas concorrentes não compartilham escopo entre usuários.
