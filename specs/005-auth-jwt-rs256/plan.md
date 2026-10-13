# Plano de migração para RS256/JWKS

Base: branch `refactor` criada da `main` no commit `47ee5df`, com `fix(auth)` integrada. Este plano segue a [especificação](spec.md). A implementação está no repositório; faltam os valores literais da Auth para ativá-la em ambiente real.

## Ordem de execução

1. **Alinhar a base.** Integrar a branch `fix(auth)` à `refactor`, trazendo API, autenticação e consumidores. Revisar dependências e testes antes de trocar o verificador.
2. **Fechar o contrato com a Auth.** Registrar issuer literal, JWKS URI, `kid`, política de relógio e rotação. Confirmar `aud` como array, os sete claims e `exp = iat + 300`. O `sub` já foi definido como `user_account.id` decimal em string.
3. **Refatorar configuração e verificador.** Substituir `JWT_SECRET` por issuer/JWKS/audience configurados. Criar cliente JWKS reutilizável com timeout/cache; escolher chave pelo `kid` somente dentro do JWKS configurado. Decodificar com `algorithms=["RS256"]`, `issuer` e `audience` fixos. Exigir claims e validar tipos/regras que a biblioteca não impõe automaticamente. Remover `verify_exp=False`.
4. **Ligar identidade e autorização.** Construir principal com `sub` e email verificados. Consultar `user_account.id`; retornar 401 para email divergente ou conta inativa. Carregar cargo e IDs de lojas ativas via `user_store`/`store`; sem loja ativa, retornar 403. Passar email, cargo e lojas ao grafo, mantendo filtros comerciais no repositório.
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
| Email da claim divergente da conta encontrada por `sub`; conta ausente | 401; grafo não executa |
| Conta inativa | 401; grafo não executa |
| Sem loja ativa | 403; grafo não executa |
| Lojas ativas | IDs seguem no grafo; consultas comerciais respeitam o escopo |
| JWT válido, cargo sem acesso | 403 conforme autorização existente |

## Riscos de integração

- `main` não contém auth: implementar só o decoder criaria código sem rota protegida para validar.
- Usar apenas email ignora o `sub` que identifica `user_account.id` e pode associar conta errada após mudança de email.
- Consultar JWKS a cada requisição eleva latência; cache sem expiração/rotação pode conservar chave retirada.
- Após o corte, tokens HS256 antigos recebem 401; coordenar emissor, API, aplicativo e deploy.
- `jti` único no emissor não bloqueia replay durante os cinco minutos; revogação/anti-replay é decisão separada.

## Evidências de conclusão

PR/commits da integração e verificador; configuração de exemplo; testes negativos e de rotação aprovados; demonstração de 401 para expirado/inválido e aceitação para RS256 válido; SDD e contrato HTTP atualizados.
