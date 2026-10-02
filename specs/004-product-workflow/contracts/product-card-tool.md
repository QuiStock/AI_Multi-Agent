# Contract: Product Card Lookup

**Status**: regras `confirmado` são normativas; mapeamento inicial conferido contra `Quistock/quistock-updated.sql`. A correspondência do schema implantado com esse script ainda deve ser validada na implantação.

## Caller and authorization

- Only the registered `product_workflow` executor may invoke this named capability.
- Inputs are the normalized product query and server-derived authenticated context. Email, role and store scope are never tool arguments controlled by the model or client.
- Role mapping: `2` manager, `3` employee.
- Employee visibility: `available_for_triage` only. Manager visibility: `SENT_TO_MANAGER` only.
- Store scope is derived and enforced server-side for every query and candidate. No cross-store retrieval.

## Request (logical)

```json
{
  "product_query": "string"
}
```

The tool receives authenticated principal/context through trusted dependency injection, not through this model-facing argument. It must not accept SQL, table names, filters, role, store IDs, or arbitrary product/suggestion IDs from the LLM.

## Response (logical)

Result must use the repository `ToolResult[DataT]` envelope (`schema_version`, `status`, `response`, `data`, `actions`, `evidence`, `warnings`, `error`, `meta`). Domain outcomes live in a typed `data.outcome` (`found`, `ambiguous`, `not_found`); do not add new top-level `ToolResult.status` values. The tool must distinguish:

- `success` with `data.outcome=found`: exactly one matching, authorized, current product card.
- `partial` with `data.outcome=ambiguous`: multiple distinct product matches, each with an opaque internal reference and only the display fields needed to distinguish it (for example name/category/SKU); evidence also contains only these minimal candidate fields so the judge can validate the clarification; no answer should be drafted as if one had been selected.
- `success` with `data.outcome=not_found`: no matching authorized card.
- `error`: dependency, timeout, authorization or internal failure, with safe stable error code and no data leak.

## Query behavior

- Fixed, parameterized, read-only SQL only; no model-generated SQL.
- Return only fields needed to construct the same structured card contract used by the request snapshot.
- Exclude any suggestion with a related `suggestion_log` event `EXPIRED`.
- Role 3: `available_for_triage = TRUE`; role 2: `status = 'SENT_TO_MANAGER'`.
- Escopo: `user_account.email` → `user_account.id` → `user_store.user_id`, somente vínculo ativo/não desvinculado, comparando `user_store.store_id` com `suggestion.store_id`.
- Dados: `suggestion.product_id` → `product.id`; `product.category_id` → `category.id`; `suggestion_log.suggestion_id` exclui qualquer `event = 'EXPIRED'`.
- A consulta limita resultados a seis produtos, configura `statement_timeout` e aplica pesquisa parametrizada em `product.name`, `product.sku` e `category.name`.
- O campo visual “Validade” é vencimento físico: `MIN(batch.expiration_date)` por produto/loja considerando apenas lote ativo com saldo positivo. Não confundir com `suggestion.promotion_valid_until`, que é validade da promoção. Caso não exista lote ativo, a validade fica ausente.
- A quantidade/desconto SQL usam `current_*` quando preenchidos e, senão, `ml_*`; essa precedência ainda precisa ser comparada visualmente com o card real do frontend antes de produção.

Initial script mapping: `suggestion.product_id -> product.id`, `suggestion_log.suggestion_id -> suggestion.id`, `product.category_id -> category.id`, `batch(product_id, store_id, expiration_date)` for physical validity, and store authorization via `user_account` plus active `user_store` links. `product` exposes `name` and `sku`, but no explicit presentation/packaging column. `suggestion` exposes `current_batch_count`/`ml_batch_count` and promotion discount/price/validity fields. The exact mapping to frontend card labels and current-vs-ML value precedence must match the app's existing card contract.

## Ambiguity and user selection

When needed, the response renders options using only the fields necessary to distinguish them (such as product name, category, and SKU if still needed) and asks the user which one they mean. It does not call a second LLM selection tool and creates no dedicated persisted pending-selection state. On the next turn, the workflow uses ordinary conversation context to understand the user's choice and runs a fresh lookup under current server-derived authorization before answering. If the available context does not make the choice clear, it asks the user to identify the product again; it never silently chooses one.

The resolution may be implemented in the existing workflow/executor; no API field, graph-persisted pending list, Mongo field, or additional tool is required by this contract.

## Evidence

Each selected card returned by the SQL tool must yield a stable evidence ID and metadata identifying source as `product_card_query`. Snapshot-derived evidence must identify source as `client_card_snapshot`. Judge validates claim support against the cited payload, not external truth.
