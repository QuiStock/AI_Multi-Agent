# Research: Autenticação e identidade na API de IA

## Decisões e evidências

### R1 — Formato da credencial

- **Decision**: JWT criptografado (JWE) recebido como Bearer, `alg=RSA-OAEP-256`, `enc=A256GCM`, biblioteca Python `jwcrypto`; a API armazena a chave privada RSA em `.env` e consome apenas `email`. O emissor criptografa para a chave pública correspondente. Tokens expirados são barrados antes da API.
- **Rationale**: JWE é o formato padronizado para conteúdo JWT criptografado. `RSA-OAEP-256` protege a chave de conteúdo usando OAEP/SHA-256; RSA requer chave de pelo menos 2048 bits na especificação JWA. `A256GCM` oferece criptografia autenticada com chave de conteúdo AES de 256 bits. A biblioteca `jwcrypto` documenta suporte a ambos os algoritmos.
- **Alternatives considered**: JWS com verificação de assinatura, rejeitado porque o requisito é descriptografar. Rotação sem identificador exige tentativa sequencial de descriptografia com várias chaves; foi preferido `kid` no cabeçalho protegido para seleção explícita.
- **Sources**: [RFC 7516 — JWE](https://www.rfc-editor.org/info/rfc7516/), [RFC 7518 — JWA](https://www.rfc-editor.org/info/rfc7518/), [jwcrypto JWE documentation](https://jwcrypto.readthedocs.io/en/v1.3.0/jwe.html).

### R2 — Limite da consulta PostgreSQL

- **Decision**: acesso direto da API de IA com credencial exclusiva de leitura; buscar apenas `email` e `role_id` em `user_account`; a API Spring mantém a propriedade do schema.
- **Rationale**: corresponde à decisão confirmada e reduz o alcance da credencial. PostgreSQL permite conceder `SELECT` ao nível da tabela ou de colunas; privilégios amplos e superusuário não são necessários para o caso.
- **Alternatives considered**: pedir validação à API Spring; não escolhido pelo usuário. Conceder escrita/DDL; explicitamente proibido.
- **Sources**: [PostgreSQL GRANT](https://www.postgresql.org/docs/current/sql-grant.html), [PostgreSQL SET TRANSACTION](https://www.postgresql.org/docs/17/sql-set-transaction.html).

### R3 — Adaptador de banco

- **Decision**: adicionar ao serviço um adaptador PostgreSQL isolado, com timeout, consulta parametrizada de leitura e teste de integração. A biblioteca concreta e o modo de pool devem ser fechados junto à revisão técnica e compatibilidade do deploy.
- **Rationale**: `pyproject.toml` não contém driver PostgreSQL; endpoints/serviços existentes são predominantemente síncronos, portanto um driver síncrono é opção inicial compatível, sem impedir evolução. Psycopg documenta pool síncrono para concorrência por threads e contextos para devolver conexões com segurança.
- **Alternatives considered**: usar API Spring; rejeitada para esse lookup conforme ownership aprovado. Acesso via SQL montado; rejeitado em favor de parâmetros.
- **Source**: [Psycopg 3 connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

### R4 — Propagação da identidade

- **Decision**: converter a identidade externa e todos os limites de persistência/jobs para email na mesma entrega, sem aceitar o `user_id` do cliente como fallback.
- **Rationale**: evita divergência entre autorização e chave de isolamento da memória. Spec 003 já registra identidade email e início com coleções vazias; não fazer backfill.
- **Alternatives considered**: manter `user_id` internamente após autenticar email; rejeitado porque o usuário determinou email como identificador em todo o fluxo.

### R5 — Readiness de provedores de modelos

- **Decision**: health reporta a disponibilidade de Gemini e Groq junto aos stores. Usa os endpoints de listagem de modelos dos dois provedores, com timeout limitado, sem chamar geração de conteúdo.
- **Rationale**: mantém `/health` sem custo/efeito de inferência e verifica credencial/conectividade real, não apenas presença da chave.
- **Alternatives considered**: validar apenas presença de API key; insuficiente para afirmar disponibilidade do provedor. Fazer geração de texto em toda chamada; desnecessário e potencialmente oneroso. A listagem oficial de modelos permite uma probe de leitura.
- **Sources**: [Gemini API — models.list](https://ai.google.dev/api/models), [Groq API — list models](https://console.groq.com/docs/api-reference).

## Gate antes da implementação

**Gate fechado para planejamento**: usuário aprovou rotação com `kid` protegido, convivência temporária das chaves antiga/nova e retirada da antiga após expirar a janela de encaminhamento; comprometimento confirmado exige revogação imediata. O operador mantém os valores e o formato concreto no `.env`, fora do escopo de alteração por esta feature. A versão compatível de `jwcrypto` será selecionada e travada em `pyproject.toml`/`uv.lock` durante a implementação, validando compatibilidade com a versão Python do projeto. A garantia de que tokens expirados são barrados antes da API permanece requisito do emissor/encaminhamento.
