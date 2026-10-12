# Tarefas e gates

Itens dependentes de decisões abertas só entram em execução depois que elas forem registradas em `spec.md`.

| ID | Entrega | Dependência | Estado |
| --- | --- | --- | --- |
| AUTH-T01 | Definir integração da API/auth existente à `refactor` e revisar diff | Branch/PR de origem | aberto |
| AUTH-T02 | Registrar issuer, JWKS URI e política de `kid`/rotação | Equipe Auth | aberto |
| AUTH-T03 | Decidir divergência entre email assinado/local e regra para usuário inativo; `sub = user_account.id` já confirmado | Equipes Auth/API | aberto |
| AUTH-T04 | Decidir relógio, limite de duração e falha de JWKS | Equipes Auth/API | aberto |
| AUTH-T05 | Implementar verificador RS256/JWKS, configuração e respostas HTTP | T01, T02, T04 | planejado |
| AUTH-T06 | Migrar principal, consulta de conta e consumidores sem ampliar acesso | T01, T03 | planejado |
| AUTH-T07 | Atualizar ambiente, deploy, documentação e auditoria | T05, T06 | planejado |
| AUTH-T08 | Executar testes unitários, HTTP, rotação e regressão; anexar evidências | T05 a T07 | planejado |

Rastreabilidade: T05 cobre RF-AUTH-001/002/003 e RNF-AUTH-001; T06 cobre RF-AUTH-004; T07 cobre RNF-AUTH-002; T08 comprova CA-AUTH-001 a 005.
