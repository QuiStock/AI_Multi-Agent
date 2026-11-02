# AI_Multi-Agent

## Publicação de imagem ARM64

Veja [publicação e preparação do Infra](docs/container-release.md) para releases,
execução manual, referência por digest e permissões do GHCR/Infra.

## AWS deployment operations

`Dockerfile.observer` serves the separate frontend under `/observe/` on port 8080.
The gateway must preserve `/api/v1/observability`, including the session cookie Path;
set `OBSERVABILITY_FRONTEND_ORIGIN` to its exact HTTPS origin. API containers use
`PORT=8000` in Kubernetes. The worker has a separate image and requires no Observe
session secret or TypeSafe credential.

Run `python -m src.ops.memory --check --vector-size 768` before initializing new,
empty memory with `--apply`. Existing populated memory requires a separate migration.
Run `python -m src.ops.faq --check` before `--apply`; check validates bundled documents
and the existing vector dimension without calling an embedding API. Apply uses Gemini,
persists the FAQ manifest in MongoDB, and refuses populated FAQ without a compatible
manifest. Execute only one FAQ apply Job at a time. Back up shared external databases
before migrations; no operation here creates `public.super_admin` or its credentials.
