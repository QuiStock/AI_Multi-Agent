# Decisões de implementação: autenticação HS256

## R1 — Formato do token

- **Decisão confirmada**: receber JWT assinado com `HS256`; a API de IA valida a assinatura com `JWT_SECRET` compartilhado pelo emissor e extrai somente `email`.
- **Validade temporal**: a API de IA não valida `exp`. O emissor/encaminhador garante que só tokens válidos chegam à API.
- **Motivo da simplificação**: há um emissor e um consumidor acordados para este fluxo; o segredo compartilhado reduz a configuração necessária. O segredo fica somente nos serviços, não no frontend.
- **Alternativa substituída**: JWE com RSA, keyring, rotação por `kid` e descriptografia local.
- **Referência**: [RFC 8725 — JWT Best Current Practices](https://www.rfc-editor.org/rfc/rfc8725.html).

## R2 — Consulta e autorização da conta

- A API consulta diretamente `user_account.email` e `user_account.role_id` com credencial exclusiva somente de leitura.
- A API Spring continua responsável pelo schema. A API de IA não executa escrita, DDL ou concessão de privilégios.
- A role do banco é a fonte de autorização. A regra atual nega `role_id = 1` e permite os demais.

## R3 — Fronteira de autenticação

- `JWTEmailDecoder` valida token e extrai email.
- `AuthenticationService.authenticate(token)` coordena decoder, repositório e criação do principal.
- `get_authenticated_principal` recebe Bearer e converte erros internos em status HTTP; não duplica a validação.
- O repositório executa SQL parametrizado com timeout. Erro de lookup falha fechado.
