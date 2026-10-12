# Plano de migração para RS256/JWKS

Base: branch `refactor` criada da `main` no commit `47ee5df`. Este plano segue a [especificação](spec.md); a implementação depende da integração da API e das decisões sobre Auth e identidade.

## Ordem de execução

1. **Alinhar a base.** Integrar `src/api/`, `src/auth/` e consumidores da feature de API/autenticação à `refactor` por PR/merge coordenado. Revisar dependências e testes antes de trocar o verificador. Copiar apenas `token.py` deixaria principal, repositório e rotas sem contrato consistente.
2. **Fechar o contrato com a Auth.** Registrar issuer literal, JWKS URI, `kid`, política de relógio e rotação. Confirmar `aud` como array, os sete claims e `exp = iat + 300`. O `sub` já foi definido como `user_account.id` decimal em string.
3. **Refatorar configuração e verificador.** Substituir `JWT_SECRET` por issuer/JWKS/audience configurados. Criar cliente JWKS reutilizável com timeout/cache; escolher chave pelo `kid` somente dentro do JWKS configurado. Decodificar com `algorithms=["RS256"]`, `issuer` e `audience` fixos. Exigir claims e validar tipos/regras que a biblioteca não impõe automaticamente. Remover `verify_exp=False`.
4. **Ligar identidade e autorização.** Construir principal com `sub` e email verificados. Converter `sub` para `BIGINT` válido e consultar `user_account.id`; conferir consistência do email conforme a política ainda pendente. Não usar `role_id` do token nem campos do body como autoridade.
5. **Uniformizar HTTP e operação.** Mapear JWT inválido/expirado para 401 com `WWW-Authenticate: Bearer`; manter 403 para principal válido sem permissão. Separar configuração/JWKS indisponível de credencial inválida. Atualizar `.env.example`, deploy, documentação e auditoria.
6. **Verificar.** Testes unitários com RSA/JWKS local e relógio controlado; testes HTTP com grafo espião; integração com chaves rotacionadas; regressão de autorização entre usuários/lojas. Testes automáticos não dependem da Auth real.

## Matriz mínima de testes

| Caso | Resultado |
| --- | --- |
| RS256 válido, `kid` publicado e claims corretas | Acesso conforme cargo e loja |
| Bearer ausente; JWT malformado; HS256, `none` ou outro algoritmo | 401; grafo não executa |
| Assinatura adulterada; `kid` não publicado; JWK incompatível | 401; grafo não executa |
| `iss` errado; `aud` errado/ausente; claim obrigatória ausente ou tipo inválido | 401; grafo não executa |
| `exp` vencido; `iat` futuro; duração excessiva se aprovada | 401; grafo não executa |
| Chave nova publicada e chave antiga depois removida | Cache respeita rotação |
| JWKS indisponível, com/sem chave válida em cache | Resposta operacional definida e testada |
| `sub`/email divergentes; conta ausente/inativa | Sem identidade ou escopo alheio |
| JWT válido, cargo sem acesso | 403 conforme autorização existente |

## Riscos de integração

- `main` não contém auth: implementar só o decoder criaria código sem rota protegida para validar.
- Usar apenas email ignora o `sub` que identifica `user_account.id` e pode associar conta errada após mudança de email.
- Consultar JWKS a cada requisição eleva latência; cache sem expiração/rotação pode conservar chave retirada.
- Após o corte, tokens HS256 antigos recebem 401; coordenar emissor, API, aplicativo e deploy.
- `jti` único no emissor não bloqueia replay durante os cinco minutos; revogação/anti-replay é decisão separada.

## Evidências de conclusão

PR/commits da integração e verificador; configuração de exemplo; testes negativos e de rotação aprovados; demonstração de 401 para expirado/inválido e aceitação para RS256 válido; SDD e contrato HTTP atualizados.
