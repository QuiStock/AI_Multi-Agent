# Autenticação da API de IA por JWT RS256

Status: **planejada**. A mudança para RS256/JWKS foi solicitada em 2026-10-12; parâmetros da integração ainda estão abertos.

## Estado atual

- A branch `main` (`47ee5df`) ainda não contém `src/api/` nem `src/auth/`. A implementação da API e da autenticação está em branches posteriores, incluindo `fix(auth)` e `a2a`.
- Nessa implementação, `src/auth/token.py` aceita HS256 com segredo compartilhado, extrai `email` e desativa `verify_exp`; `src/auth/service.py` consulta `user_account` por email para obter o cargo.
- O JWT humano das rotas da API de IA é distinto das credenciais A2A entre serviços.

## Contrato

| Campo | Regra | Status |
| --- | --- | --- |
| Header `alg` | `RS256`, único algoritmo permitido | confirmado |
| Header `kid` | Identifica chave pública para rotação | proposto; confirmar com a Auth |
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

**RF-AUTH-004 — Identidade:** `sub` identifica `user_account.id` (`BIGINT`) e é transportado no JWT como string decimal. A API consulta a conta local por esse ID; um `sub` fora do formato/intervalo da chave ou sem conta correspondente é inválido (401). A claim assinada `email` continua obrigatória e disponível ao principal autenticado para os fluxos atuais de conversa e memória. Cargo e escopo de loja vêm da conta no servidor; claims ou campos livres do cliente não ampliam permissões. A política para divergência entre email assinado e email local ainda precisa ser decidida.

**RNF-AUTH-001 — Chaves:** o JWKS usa origem configurada e confiável, HTTPS fora do ambiente local, timeout, cache limitado e atualização controlada na rotação de `kid`. A chave privada não fica na API de IA. Falha do JWKS sem chave válida em cache é indisponibilidade de dependência (HTTP 503 proposto); `kid` desconhecido após consulta bem-sucedida é credencial inválida (401).

**RNF-AUTH-002 — Observabilidade:** registrar categorias de rejeição e falha do JWKS sem JWT bruto, email, `sub` ou chave. `jti` único não implica, sozinho, proteção contra replay.

## Critérios de aceite

- **CA-AUTH-001:** JWT RS256 válido, com claims e chave publicada no JWKS, autentica o usuário e mantém a autorização por cargo/loja.
- **CA-AUTH-002:** JWT expirado, adulterado, com `alg` diferente, `kid` desconhecido, `iss`/`aud` incorretos ou claim obrigatória ausente retorna 401 sem executar o grafo.
- **CA-AUTH-003:** a rotação aceita chaves antigas e novas enquanto publicadas e deixa de aceitar uma chave após sua retirada efetiva, conforme a política de cache.
- **CA-AUTH-004:** configuração ausente ou falha de rede do JWKS não aceita o token por suposição; sua resposta operacional é testada separadamente de credencial inválida.
- **CA-AUTH-005:** `sub`/email divergentes ou conta inexistente/inativa não atribuem identidade nem cargo de outro usuário; o teste exato depende do mapeamento.

## Decisões pendentes

1. Valor literal de `iss`, URL HTTPS do JWKS e vínculo confiável entre ambos.
2. Política para email assinado divergente do email armazenado e para contas inativas.
3. Tolerância de relógio e verificação de `exp - iat <= 300` no consumidor.
4. Política de cache/rotação e comportamento com JWKS indisponível.
5. Se `jti` será apenas validado estruturalmente ou usado para revogação/anti-replay.
6. Qual branch/PR trará a API e a autenticação existente à base `refactor`; não incorporar toda a branch `a2a` só para obter auth.

## Referências técnicas

- [RFC 7519 — claims JWT](https://www.rfc-editor.org/rfc/rfc7519.html)
- [RFC 8725 — boas práticas de algoritmo, issuer e audience](https://www.rfc-editor.org/rfc/rfc8725.html)
- [PyJWT — uso de `PyJWKClient`, claims obrigatórias e RS256](https://pyjwt.readthedocs.io/en/latest/usage.html)
