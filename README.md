# QuiStock AI API

<img src="src/observability/front-observer/public/assets/quistock-feather.svg" alt="QuiStock" width="64">

![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141%2B-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-product%20workflow-4169E1?logo=postgresql&logoColor=white)

Serviço de conversação e fluxos de IA do QuiStock. A API FastAPI coordena agentes com LangGraph, protege entradas e respostas e integra memória, FAQ e consultas comerciais somente leitura.

## Capacidades

- **FAQ com RAG:** recupera documentos no Qdrant e responde com base nas evidências encontradas, respeitando o público do documento.
- **Product Workflow:** consulta sugestões e promoções no PostgreSQL em modo somente leitura; exige perfil de gerente ou funcionário.
- **Conversas:** expõe rotas para enviar mensagens, listar conversas e consultar histórico. MongoDB guarda mensagens e metadados de jobs.
- **Memória e resumos:** Redis Streams transporta jobs; Qdrant guarda resumos pesquisáveis. O checkpointer local usa `MemorySaver` em desenvolvimento e testes.
- **Observabilidade:** publica traces, métricas e logs correlacionados na API.

O fluxo ativo é composto por guardrails, router, agentes especializados e compiler/judge. MCP continua planejado, não é uma capacidade ativa.

## Tecnologias e serviços

- Python 3.14+, FastAPI e Uvicorn
- LangGraph e LangChain para orquestração e integrações de modelos
- OpenAI para chat e resumos; Gemini para embeddings de FAQ e memória
- MongoDB, Redis e Qdrant para conversas, fila de resumos e busca vetorial
- PostgreSQL para consultas do Product Workflow, com credencial somente leitura

## Configuração local

Requisitos: Python 3.14, [uv](https://docs.astral.sh/uv/) e os serviços usados pela capacidade que será executada. O arquivo `.env.example` lista as variáveis disponíveis; configure as chaves de provedor e os serviços necessários sem commitar segredos.

```bash
uv sync
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Com a API em execução, a documentação OpenAPI fica disponível em `/docs`. O Product Workflow requer `POSTGRES_DSN`; FAQ e memória dependem dos serviços vetoriais e de persistência correspondentes.

## Testes

```bash
uv run pytest
```

Por padrão, pytest exclui os testes marcados como integração. Para executá-los, use `uv run pytest -m integration`; esses testes podem depender do Docker.

## Estrutura

| Diretório | Responsabilidade |
| --- | --- |
| `src/api/` | Rotas HTTP, schemas, dependências e serviços da API |
| `src/graphs/` | Estado e composição do grafo LangGraph |
| `src/agents/` | Router, FAQ, Product Workflow, compiler e judge |
| `src/guardrails/` | Validação de entrada e saída |
| `src/memory/` | Persistência, resumos e retomada de conversas |
| `src/observability/` | Traces, métricas, logs e frontend de observabilidade |
| `tests/` | Testes unitários, de contrato e de integração |

## Containers

Os Dockerfiles da API e dos workers estão na raiz. Para releases de imagem ARM64, publicação no GHCR e permissões de infraestrutura, consulte [publicação e preparação do Infra](docs/container-release.md).
