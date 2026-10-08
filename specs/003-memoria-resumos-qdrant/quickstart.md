# Quickstart: Validate Conversation Memory Persistence

**Feature**: `003-memoria-resumos-qdrant`

This guide is the post-implementation validation path. Commands are documented here but were not run while creating the plan.

## Prerequisites

- Python 3.14 and `uv` available.
- Project's locked dependencies installed with `uv sync --locked`.
- Redis local disponível no Docker Compose; MongoDB e Qdrant acessíveis pelas
  URLs configuradas no `.env`. As URLs e coleções devem poder mudar por
  ambiente sem alteração de código.
- Integration tests use the `integration` pytest marker and may require Docker
  for the Redis service.
- Environment points to isolated test data; never run collection recreation/destructive cutover checks against production by default.

## Unit and contract checks

```powershell
uv run pytest tests/test_memory_message_service.py tests/test_memory_summary_context.py tests/test_qdrant_summary_indexer.py tests/test_summary_jobs.py tests/test_summary_job_worker.py
```

Expected outcomes:

- one conversation document contains the ordered message array and no summary fields;
- repeated message IDs and repeated completed jobs are idempotent;
- Qdrant point identity is stable and watermark never regresses;
- retry-exhausted jobs are observable/reprocessable;
- semantic and recent fallback responses obtain summary text from Qdrant and validate owner/status;
- deletion and replayed/stale jobs converge to no Mongo conversation and no Qdrant summary point.

## MongoDB integration

```powershell
uv run pytest -m integration tests/integration/test_memory_mongo_repository.py
```

Verify email-based conversation ownership, message append order, idempotent append, empty new collections before cutover, and restartable deletion tombstones.

## End-to-end worker and fresh collection cutover checks

Run the API and summary worker in separate terminals/processes. The API persists the
closure/job and returns `202`; the worker runs the Redis Streams consumer and
Mongo outbox relay:

```powershell
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
uv run quistock-summary-worker
```

Em uma execução manual do reconciliador, use:

```powershell
uv run quistock-memory-reconcile
```

Para solicitar exclusão, use `DELETE
/api/v1/conversations/{conversation_id}` com o Bearer JWE do próprio usuário.
O retorno `202` confirma apenas a criação/recuperação do job; a ausência nos
dois stores deve ser verificada após o worker convergir.

Configure o mesmo `.env` para API e worker, com Redis apontando para o serviço
local do Docker Compose e MongoDB/Qdrant apontando para os endereços do
ambiente atual. Redis Streams requires Redis Server 5.0 or newer.

```powershell
uv run pytest tests/test_conversation_end_api.py tests/test_summary_job_worker.py tests/test_summary_jobs.py
uv run pytest -m integration
```

Use disposable MongoDB/Redis/Qdrant collections. Inject failures at (1) job persistence, (2) Redis publication, (3) summary generation, (4) Qdrant upsert/verification, and (5) deletion between stores. Re-run the worker/reconciler and confirm eventual convergence without putting summary text in MongoDB.

The user-approved cutover discards prior conversation history and starts with empty MongoDB/Qdrant collections. Verify exact environment and collection identifiers before any physical removal; no backfill or history restoration is performed.

## Static and full regression checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## Evidence to retain

- test output linked to FR-001–FR-016;
- proof that newly provisioned collections start empty and store the authenticated email as user identity;
- Qdrant point verification by owner/conversation/watermark;
- worker recovery and deletion-race test results.
