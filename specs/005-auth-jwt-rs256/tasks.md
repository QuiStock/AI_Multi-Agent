# Tarefas e gates

Itens dependentes de decisões abertas só entram em execução depois que elas forem registradas em `spec.md`.

| ID | Entrega | Dependência | Estado |
| --- | --- | --- | --- |
| AUTH-T01 | Integrar `fix(auth)` à `refactor` e revisar diff | Branch identificada | concluído |
| AUTH-T02 | Registrar issuer e JWKS URI literais | Equipe Auth | aberto |
| AUTH-T03 | Carregar conta ativa, cargo e lojas ativas; ausência de loja = 403 | Esquema PostgreSQL atual | concluído |
| AUTH-T04 | Aplicar `exp - iat = 300`, sem tolerância; falha de JWKS = 503 | Contrato atual | concluído |
| AUTH-T05 | Implementar verificador RS256/JWKS, configuração e respostas HTTP | T01, T04 | concluído |
| AUTH-T06 | Migrar principal e consulta por `sub`, preservando email/cargo e incluindo lojas no fluxo sem ampliar acesso | T01, T03 | concluído |
| AUTH-T07 | Atualizar ambiente, deploy, documentação e auditoria | T05, T06 | concluído no repositório; configuração real pendente |
| AUTH-T08 | Executar testes unitários, HTTP, rotação e regressão; anexar evidências | T05 a T07 | suíte local aprovada; integração PostgreSQL pendente de Docker |

Rastreabilidade: T05 cobre RF-AUTH-001/002/003 e RNF-AUTH-001; T06 cobre RF-AUTH-004/005; T07 cobre RNF-AUTH-002; T08 comprova CA-AUTH-001 a 006.

## Refatoração de autorização por código

| ID | Entrega | Estado |
| --- | --- | --- |
| AUTH-T09 | Carregar `role.code` no lookup da conta por `sub` e propagá-lo ao principal e grafo | concluído |
| AUTH-T10 | Aplicar códigos no acesso a FAQ e Product Workflow e na consulta comercial, sem IDs fixos | concluído |
| AUTH-T11 | Atualizar documentação e verificar IDs variáveis, cargos sem acesso e escopo de loja | suíte local aprovada; integração PostgreSQL pendente de Docker |
