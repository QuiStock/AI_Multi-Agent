# ADR-001: Ownership do lookup de identidade no PostgreSQL

- **Status**: Aceito
- **Data**: 2026-10-01
- **Decisores**: usuário e equipe da API de IA
- **Relacionado**: [spec.md](spec.md), FR-008, FR-013, FR-018

## Contexto

A API de IA precisa associar a claim `email` do Bearer JWE a uma conta e ler seu `role_id` em `user_account` antes de iniciar operações de conversa. O projeto possui uma API comercial Spring que mantém o domínio e schema PostgreSQL. A integração de autenticação externa não será implementada pela API de IA.

## Decisão

A API de IA mantém conexão/credencial própria, exclusiva e somente de leitura, consultando apenas `user_account.email` e `user_account.role_id`. A API Spring continua proprietária do schema e comunica mudanças de nomes/semântica que afetem essa consulta. A API de IA não executa escrita, DDL, migração ou concessão de privilégios.

Consulta precisa ser parametrizada e limitada a esses campos. Erros operacionais do banco falham fechado (`500`); conta ausente resulta `401`. Transação/probe são somente leitura. A configuração e comprovação dos grants efetivos fazem parte da validação de implantação.

## Alternativas consideradas

- A API Spring recebe uma chamada de validação da API de IA: não escolhida; a decisão acordada é conexão direta de leitura.
- Credencial ampla ou compartilhada com a aplicação comercial: rejeitada por violar privilégio mínimo e ownership.
- A API de IA tornar-se proprietária do schema: rejeitada; propriedade permanece na API Spring.

## Consequências

- A implantação precisa provisionar secret/DSN exclusivo e grants limitados a leitura de `user_account`.
- Mudanças no schema precisam de coordenação Spring–IA e testes de contrato.
- Falha/latência PostgreSQL passa a impactar autenticação da IA; usar timeouts e health checks.
- Auditoria de uso restringe-se a eventos operacionais sem token, chave ou email integral nos logs comuns; eventual requisito de auditoria de acesso a linha permanece sujeito às políticas do ambiente PostgreSQL.
- Os parâmetros JWE (`RSA-OAEP-256`, `A256GCM`), biblioteca (`jwcrypto`) e rotação por `kid` com sobreposição temporária foram decididos na spec da feature. O pool, timeouts e auditoria estão implementados e cobertos por testes. O teste PostgreSQL efêmero verifica leitura e rejeição de `UPDATE`/DDL; grants efetivos da credencial do ambiente ainda precisam ser comprovados contra o PostgreSQL de integração (T035).
