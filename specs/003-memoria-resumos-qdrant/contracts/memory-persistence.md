# Internal Contract: Conversation Memory Persistence

**Feature**: `003-memoria-resumos-qdrant`
**Scope**: contratos internos MongoDB, Redis Streams e Qdrant; não cria rota HTTP pública.

## Store ownership

- MongoDB `conversations`: one document per conversation, owner/status/title/timestamps and ordered `messages` only. No summary text, summary version, or summary watermark. **Confirmed physical field**: `messages` (2026-09-30); retain the current English timestamp/title fields and `_id` identity unless implementation inspection exposes a compatibility issue. Do not add a redundant `session_id` without a demonstrated consumer.
- MongoDB `conversation_summary_jobs`: durable job metadata only; never summary text or model output.
- Redis Stream: delivery signal containing job/conversation/owner/request identifiers, not message content or summary.
- Qdrant memory collection: summary text, embedding and summary metadata/watermark. Stable one-point-per-conversation identity.

## Append message

Input: trusted `conversation_id`, trusted `user_id`, stable `message_id`, role, content, UTC timestamp.

1. Append atomically to the conversation's message array only when the conversation is active and owned by `user_id`.
2. A repeated `message_id` is an idempotent no-op.
3. An assistant message cannot create a conversation document by itself.
4. Stored array order is authoritative for transcript order; timestamp ties must not reorder a user/assistant pair.

## End and summarize

1. The internal application boundary that ends the conversation creates one stable `closure_key` and passes it with trusted conversation/owner identifiers to the scheduler. It is not a new client-supplied field; when available, derive it deterministically from the trusted `conversation_id` and stable backend `request_id`. Retries of the same close operation reuse that key.
2. Mark the owned conversation ended, then create/get exactly one durable job for `(conversation_id, closure_key)` in MongoDB. No summary text, transcript, prompt, or model output is stored in the job.
3. A relay publishes only `job_id` to Redis Streams and records publication after `XADD`. If it crashes between those operations, duplicate publication is expected and safe; relay scans Mongo for due, unpublished jobs.
4. A consumer group claims the job with a bounded lease. Delivery is at-least-once; reclaim pending stream entries and expired Mongo leases. Acknowledge Redis only after the durable state is completed or safely moved to a retry schedule.
5. Worker validates that the conversation still belongs to the user and is ended, loads ordered messages from Mongo and the existing Qdrant point, then summarizes messages after the Qdrant watermark (or the full transcript if there is no point). A job whose conversation was resumed or removed before processing becomes `superseded`; it must not re-close the conversation or summarize an active transcript.
6. The watermark is the stable `message_id` of the last included message; resolve it against canonical Mongo array order, never timestamps. Unknown watermark is inconsistent progress and requires reconciliation, not a guessed offset.
7. Serialize updates per conversation and reread/revalidate the Qdrant point and Mongo state immediately before upsert. Never replace a later watermark. Mark the job complete only after Qdrant upsert succeeds.
8. Retry transient failures with bounded exponential backoff and `next_attempt_at`; exhausted jobs stay observable and can be explicitly requeued. Store only safe error category/type, not exception content that could contain private data.

## Summary retrieval

- Semantic candidates and their summary text come from Qdrant.
- Validate every candidate against MongoDB for current conversation existence, same owner and ended status; do not fetch summary content/version from Mongo.
- If semantic retrieval produces no valid candidate, select up to the existing limit of the user's most recently updated ended Qdrant points, excluding the current conversation. Use a payload filter and indexed `updated_at` ordering, then validate owner/status in Mongo.
- Do not make summary retrieval depend on the legacy Mongo `summary` field.

## Reconciliation

For each ended Mongo conversation, compare the last stored message with the Qdrant watermark:

- no Qdrant point: enqueue generation from transcript;
- watermark behind transcript: enqueue incremental update;
- watermark at transcript end: no-op;
- point for a missing/deleting Mongo conversation: remove point;
- malformed or inconsistent progress: report and repair from transcript or leave observable for operator review; never copy summary into Mongo.

The reconciler itself must be restartable and idempotent. Batch size, cadence and locking mechanism remain implementation parameters to validate against deployment.

## Delete

Internal delete operation accepts conversation ID and trusted owner. First atomically transition the conversation to non-readable `deleting` and persist an idempotent durable tombstone/cleanup job; only then remove the Qdrant point and Mongo conversation. Workers must acquire the same per-conversation coordination used by summary updates and revalidate owner/status plus tombstone immediately before Qdrant upsert. A tombstoned/deleting/missing conversation is never eligible for upsert. Keep the tombstone until both stores are confirmed absent; retries after partial completion converge to both absent. Reconciliation must honor tombstones and must not enqueue deleted conversations. The API/UX endpoint is outside this contract and requires a separate approved interface change.

## Legacy migration

1. Keep legacy Mongo summary fields intact until each corresponding Qdrant point is present and verified.
2. Reuse a valid point; when absent/invalid, build a fresh summary from Mongo messages and upsert it to Qdrant.
3. Read the point back and verify identity, owner, ended state and progress marker.
4. Only then unset the three legacy Mongo fields: `summary`, `summary_version`, `summarized_through_message_id`.
5. Persist a migration report of counts/errors only, not summary content; failed records remain retryable.

## Compatibility review

The user's sample uses Portuguese field names (`mensagens`, `iniciada_em`, `atualizada_em`), while the approved physical message-array key is `messages`, matching the current implementation. Preserve existing timestamp/title field names and `_id` identity; do not duplicate `_id` as `session_id` unless a consumer is demonstrated. Any contrary evidence found while implementing must be recorded and reviewed before changing persisted schema.
