# Specification Quality Checklist: Autenticação e identidade na API de IA

**Purpose**: Validar a completude e a qualidade da especificação antes do planejamento técnico
**Created**: 2026-09-30
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] A especificação descreve valor para usuário e equipe sem definir implementação de produto.
- [x] As histórias podem ser entendidas por pessoas técnicas e não técnicas.
- [x] As seções obrigatórias estão preenchidas.
- [x] Login, emissão de credenciais e ferramentas de negócio estão delimitados fora do escopo inicial.

## Requirement Completeness

- [x] Os requisitos têm identificadores estáveis e comportamento testável.
- [x] Os critérios de sucesso são observáveis e verificáveis.
- [x] As histórias principais incluem cenários de aceite.
- [x] Casos de falha e isolamento entre usuários foram identificados.
- [x] A API FastAPI de IA foi definida como responsável por validar o token em alto nível.
- [x] O fluxo acordado de recebimento do JWT criptografado (JWE) Bearer, com `RSA-OAEP-256`, `A256GCM`, biblioteca `jwcrypto`, extração exclusiva da claim `email` e rotação via `kid` foi definido; a emissão do token está fora do escopo.
- [x] A identidade é obtida somente da claim `email` do JWT; a requisição não envia `user_id`.
- [x] O email da credencial é associado à conta no PostgreSQL e propagado como identidade canônica.
- [x] O modo de acesso da API FastAPI à tabela `user_account` foi definido como consulta direta ao PostgreSQL com credenciais de ambiente.
- [x] A credencial PostgreSQL da API de IA foi definida como exclusiva e somente de leitura, sem permissões de escrita ou DDL.
- [x] O ownership do acesso direto ao PostgreSQL foi definido: credencial própria somente de leitura da API de IA; schema sob responsabilidade da API Spring.

## Feature Readiness

- [x] O caminho crítico de requisição válida e falhas está descrito (`401` para token inválido ou email sem conta; `403` para `role_id = 1` (gerente regional); `500` para instabilidade do PostgreSQL e dependência indisponível no health).
- [x] A dependência de autenticação e o limite antes do grafo estão explícitos.
- [x] As tarefas desta feature podem ser separadas da criação de Product Workflow.
- [ ] O contrato de identidade está pronto para planejamento técnico/implementação completa; detalhes técnicos permanecem explicitamente abertos nesta etapa.

## Notes

- Decisões confirmadas: API de IA recebe JWT criptografado (JWE) Bearer com `RSA-OAEP-256` e `A256GCM`, usa `jwcrypto`, chave privada fornecida por ambiente e somente a claim `email`; consulta diretamente `user_account.email` e `role_id` no PostgreSQL com credencial exclusiva somente de leitura e sem DDL. O emissor usa a chave pública correspondente; rotação por `kid` mantém as chaves antiga e nova durante a janela de transição, com revogação imediata em comprometimento. O operador fornece a configuração operacional de `.env`. Tokens expirados são barrados antes de chegar à API e não são validados por ela. Email é a identidade canônica e `user_id` não será enviado nem usado como identificador de usuário; token ausente/inválido/indecriptável ou email sem conta retorna `401`, `role_id = 1` (gerente regional) retorna `403`, instabilidade do PostgreSQL retorna `500`. `/health` verifica PostgreSQL, MongoDB, Redis, Qdrant, Gemini e Groq e retorna `500` se qualquer dependência falhar. As novas coleções de memória começam com email como identidade; o histórico antigo será descartado sem backfill. API externa não será implementada. A API Spring mantém a propriedade do schema e comunica alterações relevantes.
