# Implementation Plan: Autenticação e identidade na API de IA

**Branch**: `002-autenticacao-api-ia` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Proteger as operações de conversa FastAPI antes de qualquer execução do grafo. A API valida um JWT criptografado (JWE), extrai `email`, consulta `user_account.email` e `role_id` no PostgreSQL com credencial própria somente de leitura, rejeita `role_id = 1` e propaga o email validado como identidade canônica em todas as operações de conversa, memória e jobs. `/health` sinaliza prontidão somente quando a API e suas dependências configuradas estão disponíveis.

## Technical Context

**Language/Version**: Python 3.14 (conforme `pyproject.toml`)
**Primary Dependencies**: FastAPI, Pydantic Settings, pytest, Psycopg 3 e `jwcrypto` para PostgreSQL e JWE.
**Storage**: PostgreSQL (`user_account`, leitura de `email` e `role_id`); MongoDB, Qdrant e Redis permanecem stores já usados pelo serviço, com email como identidade.
**Testing**: pytest unitário, contrato e integração; dependências externas substituídas por doubles nos testes unitários e provisionadas em testes marcados como integração.
**Target Platform**: API Python executada localmente ou em ambiente de aplicação/container.
**Project Type**: Serviço web FastAPI existente em `src/`.
**Performance Goals**: Sem meta numérica definida; a consulta de autorização ocorre antes do grafo e deve ter timeout limitado e observável.
**Constraints**: Falha fechada; sem dados sensíveis em logs; a API de IA não escreve no PostgreSQL; histórico legado de memória não é migrado; tokens expirados não chegam à API; chave privada RSA fornecida por ambiente, claim única `email`, `RSA-OAEP-256`, `A256GCM` e `jwcrypto` confirmados; rotação usa `kid` protegido e convivência temporária de chaves. Valores e formato operacional de `.env` são responsabilidade do operador.
**Scale/Scope**: Rotas de conversa atuais, identidade propagada ao grafo e stores/jobs de memória existentes, mais endpoint operacional `/health`.

## Constitution Check

- **I. Spec-first**: PASS — spec clarificada antes do plano.
- **II. Decisões explícitas**: PASS — algoritmos, biblioteca, rotação por `kid`, convivência e retirada de chave definidos; configuração operacional de `.env` fica com o operador e não bloqueia planejamento/implementação.
- **III. Contratos/ownership**: PASS — API de IA possui credencial apenas de leitura; API Spring mantém o schema e comunica mudanças. O serviço de IA consulta apenas `user_account.email` e `role_id`.
- **IV. Fail-safe**: PASS — credencial inválida, conta não encontrada, papel bloqueado e falha de banco não iniciam o grafo; health usa readiness explícita.
- **V. Identidade/privacidade**: PASS — email vem do claim JWE e é a única identidade confiável; erros e telemetria não registram token nem segredo.
- **VI. Testes/evidência**: PASS — tasks exigem testes de contrato, isolamento, falhas e quickstart reproduzível.

## Design Decisions

1. **Autenticação como dependência FastAPI antes dos controllers**: preserva rotas e evita que router/agente estabeleça identidade. `/health` fica fora do guard de usuário.
2. **Consulta direta e somente leitura ao PostgreSQL**: uma credencial exclusiva do serviço consulta somente `email` e `role_id`; schema é mantido pela API Spring. A consulta não faz cache de decisão de papel no desenho-base para não prolongar autorização revogada; validar custo/latência durante testes.
3. **Falha diferenciada**: token ausente/inválido/indecriptável ou email sem conta → `401`; `role_id = 1` → `403`; indisponibilidade/erro de consulta PostgreSQL → `500` sem iniciar o fluxo.
4. **Identidade canônica email**: remover `user_id` como identidade da API e renomear os campos internos persistidos para email de forma coordenada em grafo, Mongo, Qdrant e jobs. Não haverá backfill; a inicialização das novas coleções vazias segue a decisão da feature de memória.
5. **Parâmetros criptográficos**: aprovados `RSA-OAEP-256`, `A256GCM` e `jwcrypto`; a API recebe a chave privada RSA por ambiente (mínimo 2048 bits), o emissor usa a chave pública correspondente e somente `email` é consumido. Na rotação, `kid` protegido seleciona a chave privada; nova e anterior coexistem até passar a janela de encaminhamento de tokens antigos. Comprometimento exige revogação imediata. Tokens expirados são barrados antes da API. O operador fornece os valores e o formato de `.env`.
6. **Readiness**: probes limitados por timeout para PostgreSQL, MongoDB, Redis, Qdrant e provedores Gemini/Groq; health não executa conversa nem geração de texto. Gemini usa `models.list` e Groq o endpoint oficial de listagem de modelos, validando acesso sem inferência.

## Project Structure

```text
src/
├── api/
│   ├── dependencies.py           # wiring da dependência de autenticação
│   ├── errors.py                 # mapeamento seguro dos erros de auth
│   ├── routes/                   # proteger rotas de conversa; health operacional
│   ├── schemas/                  # retirar user_id dos requests públicos
│   └── services/                 # consumir identidade autenticada
├── auth/                         # validação JWE, principal e lookup PostgreSQL
├── config.py                     # variáveis e validação de configuração
├── graphs/                       # estado/adaptadores propagam email
└── memory/                       # repositories, payloads e jobs identificados por email
tests/
├── test_auth_*.py                # unitários/contrato de auth
├── test_health_api.py            # readiness e falhas
└── test_*memory*.py              # isolamento por email e regressão de persistência
```

**Structure Decision**: manter a arquitetura modular existente em `src/`; introduzir `src/auth/` para separar a fronteira de confiança (token + lookup) da montagem de rotas e agentes. Testes permanecem nos módulos `tests/` existentes.

## Rollout and Safety

- Implementação segue as decisões criptográficas e de rotação registradas na spec; os valores secretos de ambiente devem ser fornecidos pelo operador e nunca versionados.
- Configurar segredo e DSN por ambiente; `.env.example` conterá apenas nomes/placeholders, nunca credenciais reais.
- Criar credencial PostgreSQL exclusiva, sem escrita, DDL ou `GRANT`, com privilégios limitados a `SELECT` nas colunas/tabela necessárias.
- Entregar como mudança incompatível de contrato: clientes deixam de enviar `user_id` e passam a enviar Bearer JWE; documentar essa mudança e alinhar cliente/API antes do rollout.
- Não executar migração nem apagar dados reais como tarefa desta feature. A implantação usará as coleções novas vazias já aprovadas no escopo de memória.

## Complexity Tracking

| Item | Justificativa |
|---|---|
| `src/auth/` e acesso PostgreSQL adicional | Fronteira explícita de autenticação/identidade e leitura mínima necessária, mantendo API externa de autenticação fora do serviço. |
