# Autenticação da API de IA por JWT RS256

Status: **implementada na branch `refactor`**. O issuer e a URL do JWKS devem ser fornecidos pela Auth no ambiente de implantação.

## Origem da mudança

- A branch `main` (`47ee5df`) não continha `src/api/` nem `src/auth/`; `fix(auth)` foi integrada à `refactor` como base da API.
- A implementação anterior aceitava HS256 sem verificar `exp` e consultava `user_account` por email.
- O JWT humano das rotas da API de IA é distinto das credenciais A2A entre serviços.

## Contrato

| Campo | Regra | Status |
| --- | --- | --- |
| Header `alg` | `RS256`, único algoritmo permitido | confirmado |
| Header `kid` | Identifica chave pública para rotação | obrigatório na implementação; confirmar com a Auth |
| `sub` | `user_account.id` (`BIGINT`) representado como string decimal | confirmado |
| `email` | Email do usuário | confirmado |
| `iss` | Issuer da Auth | confirmado; valor literal aberto |
| `aud` | Array `["quistock-api"]` | confirmado |
| `iat` | Instante de emissão, NumericDate | confirmado |
| `exp` | `iat + 300` segundos | confirmado |
| `jti` | ID único do token emitido | confirmado |

**RF-AUTH-001 — Assinatura:** a API verifica a assinatura RS256 com chave pública obtida de um JWKS confiável da Auth. Issuer e URL do JWKS são configurados no servidor; header e payload do token não escolhem a URL.

**RF-AUTH-002 — Claims:** a API exige `sub`, `email`, `iss`, `aud`, `iat`, `exp` e `jti`, com tipos válidos. Valida assinatura, issuer exato, `aud` exatamente igual a `["quistock-api"]` e expiração antes de criar o principal. O emissor produz `exp = iat + 300`. Verificar no consumidor a duração máxima de cinco minutos é proposto, sujeito à política de relógio.

**RF-AUTH-003 — Rejeição:** bearer ausente, malformado, com algoritmo não permitido, assinatura/chave inválida, claim obrigatória ausente ou inválida, issuer/audience incorretos, ou expirado retorna HTTP 401 com `WWW-Authenticate: Bearer`. O grafo não inicia. A resposta não revela token ou detalhes internos.

**RF-AUTH-004 — Identidade:** `sub` identifica `user_account.id` (`BIGINT`) e é transportado no JWT como string decimal. A API consulta a conta local por esse ID; um `sub` fora do formato/intervalo da chave ou sem conta correspondente é inválido (401). A claim assinada `email` continua obrigatória e disponível ao principal autenticado para os fluxos atuais de conversa e memória. Se esse email divergir do email da conta localizada por `sub`, ou se a conta estiver inativa, a API retorna 401 e não inicia o grafo. O cargo vem da conta no servidor; claims ou campos livres do cliente não ampliam permissões.

**RF-AUTH-005 — Lojas:** a API consulta os vínculos ativos de `user_store` do usuário autenticado, limitados às lojas ativas em `store`. Os IDs dessas lojas e o cargo atual seguem no principal e no contexto do grafo junto do email. Um usuário autenticado com cargo permitido, mas sem loja ativa, recebe 403. `role_id = 1` continua sem acesso às rotas de conversa (403). As consultas comerciais conservam seus filtros de autorização no repositório e respeitam os IDs de lojas do contexto; valores enviados pelo cliente não ampliam esse conjunto.

**RNF-AUTH-001 — Chaves:** o JWKS usa origem configurada e confiável, HTTPS fora do ambiente local, timeout de três segundos e cache de chaves de até cinco minutos no `PyJWKClient`, com atualização na rotação de `kid`. A chave privada não fica na API de IA. Falha do JWKS sem chave válida em cache é indisponibilidade de dependência (HTTP 503); `kid` desconhecido após consulta bem-sucedida é credencial inválida (401).

**RNF-AUTH-002 — Observabilidade:** registrar categorias de rejeição e falha do JWKS sem JWT bruto, email, `sub` ou chave. `jti` único não implica, sozinho, proteção contra replay.

## Critérios de aceite

- **CA-AUTH-001:** JWT RS256 válido, com claims e chave publicada no JWKS, autentica o usuário e mantém a autorização por cargo/loja.
- **CA-AUTH-002:** JWT expirado, adulterado, com `alg` diferente, `kid` desconhecido, `iss`/`aud` incorretos ou claim obrigatória ausente retorna 401 sem executar o grafo.
- **CA-AUTH-003:** a rotação aceita chaves antigas e novas enquanto publicadas e deixa de aceitar uma chave após sua retirada efetiva, conforme a política de cache.
- **CA-AUTH-004:** configuração ausente ou falha de rede do JWKS não aceita o token por suposição; sua resposta operacional é testada separadamente de credencial inválida.
- **CA-AUTH-005:** dado email da claim diferente do email da conta, conta inexistente ou inativa, a API retorna 401 sem executar o grafo.
- **CA-AUTH-006:** dado usuário válido com lojas ativas, email, cargo e IDs de lojas chegam ao grafo; consultas comerciais não retornam dados de outras lojas. Sem loja ativa ou com `role_id = 1`, a rota de conversa retorna 403 antes do grafo.

## Decisões pendentes

1. Valor literal de `iss`, URL HTTPS do JWKS e vínculo confiável entre ambos.
2. Tolerância de relógio entre a Auth e a API; hoje não há tolerância adicional e `exp - iat = 300`.
3. Se `jti` será usado para revogação/anti-replay; hoje é validado estruturalmente.

## Configuração de implantação

Definir `JWT_ISSUER` exatamente igual à claim `iss` publicada pela Auth e `JWT_JWKS_URL` como URL HTTPS do JWKS dessa mesma Auth. `aud` é fixo em `quistock-api`. Usar em `POSTGRES_DSN` uma conta somente leitura com `SELECT` em `user_account(id,email,role_id,status)`, `user_store(user_id,store_id,active,unassigned_at)` e `store(id,status)`; a consulta comercial também requer as tabelas já documentadas em `AGENTS.md`. Sem issuer/JWKS, a API responde 500 ao receber bearer; sem banco configurado, não autentica a conta.

## Referências técnicas

- [RFC 7519 — claims JWT](https://www.rfc-editor.org/rfc/rfc7519.html)
- [RFC 8725 — boas práticas de algoritmo, issuer e audience](https://www.rfc-editor.org/rfc/rfc8725.html)
- [PyJWT — uso de `PyJWKClient`, claims obrigatórias e RS256](https://pyjwt.readthedocs.io/en/latest/usage.html)
