# AGENTS.md

Guia para agentes que trabalham neste repositório. Descreve as regras de
negócio, ferramentas e convenções adotadas no projeto.

## Visão geral do projeto

Sistema **multi-agente**: cada agente tem um `agent_card.py` (criação do agente)
e uma pasta `tools/` (ferramentas expostas ao agente). O conhecimento é
armazenado em documentos sob `src/data/docs/` e indexado via RAG.

## Stack

- **LLM / embeddings**: Google Gemini (gratuitos)
  - Chat: `gemini-2.5-flash` (definido em `GEMINI_CHAT_MODEL` no `src/config.py`)
  - Embeddings: `models/gemini-embedding-001` (definido em `GEMINI_EMBEDDING_MODEL`)
- **Modelos**: `src/models/` — `get_chat_model()` e `get_embeddings()`
- **Framework**: LangChain + LangGraph (`langchain.agents.create_agent`)
- **Carregamento**: `PyPDFLoader` (PDF) e `TextLoader` (texto), via `langchain-community`
- **Vector store**: FAISS, persistido em `src/data/vectorstore/`
- **Chunking**: `RecursiveCharacterTextSplitter` (1000 chars, overlap 200)
- **Config**: `src/config.py` concentra todas as variáveis (via `python-dotenv`),
  com prefixo `FAQ_` para o RAG e `GEMINI_` para os modelos (ver `.env.example`)

## Agente FAQ

Arquivos relevantes:

- `src/agents/faq/agent_card.py` — cria o agente com `create_agent` e o system prompt
- `src/agents/faq/tools/faq_tool.py` — pipeline RAG completo + ferramenta `faq_search`

## Regras de negócio do agente FAQ

1. Respostas devem ser baseadas **exclusivamente** nos documentos de `src/data/docs/`,
   recuperados pela ferramenta `faq_search`.
2. Sempre citar a fonte (nome do arquivo) quando a informação vier da base.
3. Se a informação não estiver na base, o agente deve dizer que não encontrou e
   sugerir contato com o suporte — **nunca inventar** conteúdo.
4. Responder em português.
5. O re-embedding só ocorre quando a base muda: o `metadata.json` guarda um
   SHA-256 (`docs_fingerprint`) do conteúdo de `docs/`; se o fingerprint não mudou
   e o índice existe, o sistema apenas carrega o FAISS salvo.
6. `src/data/vectorstore/` é artefato gerado (não versionado); é recriado
   automaticamente na primeira execução após mudanças.

### Recuperação e qualidade

- São aceitos apenas documentos `.txt`, `.md` e `.pdf`, inclusive em subpastas
  de `src/data/docs/`.
- O fingerprint considera o caminho relativo e o conteúdo de cada documento
  suportado, usando a mesma regra de varredura do carregamento.
- A busca retorna resultados estruturados com `arquivo`, `conteudo`,
  `relevancia` e, para PDFs, `pagina`.
- Resultados abaixo de `FAQ_RETRIEVAL_MIN_RELEVANCE` são descartados. O valor
  padrão é `0.30` e deve ser calibrado com casos reais antes de alterações em
  produção.
- Casos de regressão da qualidade de recuperação ficam em
  `tests/test_rag_evaluation.py`. Inclua perguntas respondíveis, a fonte/página
  esperada e perguntas que devem ser recusadas sempre que a base ou a busca
  forem alteradas.

## Ferramentas

### `faq_search(query: str) -> str`

Busca na base de conhecimento via `similarity_search` (FAISS) e retorna os `k=4`
trechos mais relevantes com a fonte. Deve ser usada sempre que a pergunta envolver
regras, políticas, processos ou informações documentadas.

## Comandos

- Instalar dependências: `uv sync`
- Rodar testes: `uv run pytest --cov=src --cov-fail-under=80`
- Rodar testes de integração: `uv run pytest -m integration --cov=src --cov-fail-under=80`
- Lint: `uv run ruff check .`
- Type check: `uv run mypy .`
- Format: `uv run ruff format .`
