# Especificação: autenticação e identidade na API de IA

**Feature**: `002-autenticacao-api-ia`
**Status**: Implementação em andamento
**Atualizada**: 2026-10-05

## Objetivo e escopo

A FastAPI recebe um JWT Bearer emitido pelo serviço de login existente. A API de IA não faz login nem emite tokens. Antes de executar qualquer rota protegida, valida a assinatura HS256, extrai a claim `email`, consulta a conta e seu cargo em PostgreSQL e propaga a identidade resultante.

Esta revisão substitui a decisão anterior de receber JWE, descriptografar RSA, manter um keyring e fazer rotação por `kid`. O serviço emissor e seu fluxo de login permanecem fora da implementação da API de IA.

## Decisões confirmadas

- O algoritmo aceito é exclusivamente `HS256`.
- O emissor e a API de IA compartilham `JWT_SECRET` por configuração de ambiente. O segredo real não entra no Git nem no frontend.
- A API valida a assinatura e exige uma claim `email` textual e não vazia.
- A API não valida `exp`. A premissa operacional é que somente tokens válidos chegam à API. Se token expirado chegar, a API não o distinguirá de um token ainda válido com assinatura correta.
- A API consulta `user_account.email` e `user_account.role_id` com credencial PostgreSQL exclusiva e somente de leitura.
- O cargo usado para autorização vem do banco, não do corpo da requisição nem do JWT.
- `role_id = 1` (gerente regional) recebe `403`; os demais cargos são permitidos no escopo atual.
- A API de IA não emite credenciais, não altera o schema comercial e não escreve no PostgreSQL.

## Requisitos funcionais

- **FR-001**: Todas as rotas de conversa exigem Bearer JWT validado antes de iniciar memória, controller ou grafo.
- **FR-002**: A identidade canônica é o email da claim `email`, associada a uma conta existente em `user_account`.
- **FR-003**: Nenhum email, `user_id` ou cargo enviado pelo cliente pode substituir ou ampliar a identidade/cargo obtidos pelo servidor.
- **FR-004**: O servidor propaga o email autenticado para controllers, grafo, memória e jobs; o acesso a conversas fica isolado por email.
- **FR-005**: JWT ausente ou inválido, assinatura inválida, email ausente/inválido ou conta inexistente resulta em `401`.
- **FR-006**: Cargo sem permissão, inclusive `role_id = 1` na regra atual, resulta em `403` antes do processamento protegido.
- **FR-007**: Falha ou indisponibilidade na consulta PostgreSQL resulta em `500` antes do processamento protegido.
- **FR-008**: Erros públicos são genéricos; logs de auditoria registram somente códigos de motivo, nunca JWT, segredo ou email integral.
- **FR-009**: `/health` permanece sem autenticação de usuário e mantém seu contrato de readiness atual.
- **FR-010**: O PostgreSQL usado pela API de IA tem somente as permissões de leitura necessárias para o lookup de identidade.

## Critérios de aceite

1. Dado um token HS256 válido com email cadastrado e cargo permitido, quando uma rota de conversa é chamada, então o principal contém email e cargo retornados pelo banco e a operação segue.
2. Dado um token ausente, malformado, assinado com outro segredo/algoritmo, sem email válido ou com email sem conta, quando uma rota protegida é chamada, então retorna `401` e o grafo não é executado.
3. Dado um token com email de conta cujo `role_id = 1`, quando uma rota protegida é chamada, então retorna `403` e o grafo não é executado.
4. Dado que PostgreSQL falhe durante o lookup, quando uma rota protegida é chamada, então retorna `500` e o grafo não é executado.
5. Dado um token com assinatura válida, a API não faz validação local de `exp`; a validade temporal é premissa do serviço que encaminha o token.
6. Dado um cliente que inclua identidade ou cargo no corpo, quando chamar a rota, então esses campos não alteram o principal autenticado.

## Entidades

- **JWT recebido**: Bearer assinado em HS256; claim consumida: `email`. A API não emite o JWT.
- **Conta**: registro `user_account`, campos consultados `email` e `role_id`.
- **Principal autenticado**: email canônico da conta e cargo consultado no PostgreSQL.
- **Conversa**: recurso pertencente a um email e protegido por filtro de ownership.

## Fora de escopo

Login, emissão/renovação de tokens, validação local de `exp`, cadastro de usuário, alteração do schema Spring e autorização granular de cargos além da regra atual.
