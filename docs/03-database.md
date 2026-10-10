# 3. Database design

The implementation uses SQLite through `SQLiteRepository` in `src/claims_triage/repository.py`. Its `SCHEMA` string is the executable source of truth; this document describes schema version 1. Database initialization enables write-ahead logging (WAL), enables foreign keys on every connection, creates absent tables/indexes and rejects an unsupported schema-version set. SQL values are bound parameters.

## Relationships

```text
sessions 1 --- * messages
    |
    +------ * batches 1 --- * results
    |            |               |
    |            +--- * events   +--- 0..1 reviews
    |
    +------ * agent_threads (one remote thread per session/role)

history (shared synthetic prior losses; keyed by policy and claim)
metadata (JSON configuration/provisioning values)
schema_version (supported version: 1)
```

Policy coverage is intentionally a validated synthetic file catalog (`data/policy_coverage.json`), not a mutable SQL policy administration system. Knowledge is stored in versioned retrieval files. Batch evidence captures the policy/rule evidence used for a decision so an explanation does not have to reconstruct it from a later edited catalog.

## Table definitions

| Table | Columns | Keys and constraints | Purpose |
|---|---|---|---|
| `schema_version` | `version INTEGER` | Primary key; application accepts only version 1 | Explicit compatibility check; not a migration framework |
| `sessions` | `id TEXT`, `created_at TEXT`, `last_claim_id TEXT NULL`, `lease_token TEXT NULL`, `lease_until REAL DEFAULT 0` | Primary key `id`; creation time defaults to SQLite `CURRENT_TIMESTAMP` | Opaque UUID session identity, contextual claim pointer and persisted processing lease |
| `messages` | `id INTEGER`, `session_id TEXT`, `role TEXT`, `content TEXT`, `created_at TEXT` | Auto-increment primary key; session foreign key; role restricted to `user` or `assistant` | Ordered conversation memory |
| `batches` | `id TEXT`, `session_id TEXT`, `state TEXT`, `mode TEXT`, `knowledge_version TEXT`, `created_at TEXT` | Primary key `id`; session foreign key | Batch ownership, routine state, mock/Azure provenance and knowledge version |
| `results` | `batch_id TEXT`, `row_index INTEGER`, `claim_id TEXT`, `evidence TEXT` | Composite primary key `(batch_id,row_index)`; batch foreign key; `results_claim` index on `claim_id` | Original normalized result/evidence serialized as JSON; duplicate claim IDs remain separate rows |
| `events` | `id INTEGER`, `batch_id TEXT`, `sequence INTEGER`, `state TEXT`, `detail TEXT`, `created_at TEXT` | Auto-increment primary key; batch foreign key; unique `(batch_id,sequence)` | Ordered, persisted routine/checkpoint and human-decision audit events |
| `history` | `policy_number TEXT`, `claim_id TEXT`, `claim_type TEXT`, `loss_date TEXT`, `flagged INTEGER`, `note TEXT`, `source TEXT` | Composite primary key `(policy_number,claim_id)`; `flagged` restricted to 0/1 | Cross-session synthetic prior-loss memory; source is seed label or originating batch ID |
| `reviews` | `batch_id TEXT`, `row_index INTEGER`, `decision TEXT`, `note TEXT`, `reviewer TEXT`, `created_at TEXT` | Composite primary key `(batch_id,row_index)`; composite foreign key to `results` | At most one human decision per result; preserves original evidence |
| `agent_threads` | `session_id TEXT`, `role TEXT`, `thread_id TEXT` | Composite primary key `(session_id,role)`; session foreign key | Reuses a distinct Azure conversation thread for each agent role within a session |
| `metadata` | `key TEXT`, `value TEXT` | Primary key `key` | JSON values, including runtime/provisioning metadata |

Columns are non-null unless shown otherwise. JSON is stored as text for portability; the serializer rejects NaN and converts decimal values to strings. The database does not independently JSON-validate every stored text field, or enforce the application's allowed state/decision values. Those contracts are checked by the application boundary. Direct writes outside the repository bypass those application controls and are unsupported.

## Persistence contracts

**Atomic batch commit.** `save_batch` inserts the batch, all row results, ordered routine events and eligible history within one SQLite transaction. Exceptions roll back that transaction. Session creation and individual conversation messages are separate commits; they are not rolled back with a failed batch transaction. A batch interrupted before its commit has no partially successful batch record, although its session/messages can already exist.

**Stable row identity.** Claim ID cannot be a result primary key because a malformed batch may contain it more than once. The `(batch_id,row_index)` key preserves every occurrence and provides an unambiguous target for review. Same-session duplicate detection joins results to their owning batches rather than treating all historical synthetic demonstrations as one batch.

**Immutable initial evidence and one review.** `review` uses `BEGIN IMMEDIATE`, resolves the row within the specified session and rejects approval unless the stored recommendation is `auto_approve`. It inserts a single review record and a `HUMAN_DECISION` event together. A second review conflicts with the composite primary key and returns `already_reviewed`. The batch becomes `REVIEWED` only after every row has a review. Reading a batch adds the recorded review and derives the visible `review_status`; it does not rewrite the original evidence JSON.

**Long-term memory.** Seed insertion is idempotent (`INSERT OR IGNORE`). Processing history uses an upsert keyed by policy and claim. It preserves any earlier positive flag with `MAX(existing.flagged,new.flagged)`, so replaying a clean demonstration cannot erase an earlier recorded review indicator. Other existing historical fields are preserved on conflict. The repository returns policy history ordered by loss date; the domain layer additionally filters matching peril, earlier loss dates and exclusion of the current claim. History represents prior triage indicators, not an authoritative ledger of final paid/denied claims.

**Short-term memory that survives process restarts.** Messages are persisted in insertion order; reads return the latest 100 messages in chronological order. The session's `last_claim_id` supports contextual follow-ups. Azure thread IDs are persisted separately per role and do not replace local messages/evidence. The 100-message read limit is a context bound, not an automatic deletion or retention policy.

**Concurrency.** A session operation acquires a conditional persisted lease with a UUID token and a 600-second expiry; a busy session receives `session_busy`. The current owner is tracked in a context variable. Renewal requires the same stored token and an unexpired lease. Batch persistence starts an immediate transaction and checks session ownership, token and expiry before writing; an absent, expired or replaced lease fails with `lease_lost`. Release clears it only when the stored token matches the holder. SQLite serializes writes, WAL supports ordinary concurrent readers, and connections use a 10-second busy timeout. This is a single-host/local-disk design; these ownership checks do not establish a multi-region or multi-replica deployment contract.

## Operations and evolution

- Keep the database in a persistent, access-restricted directory. It contains synthetic descriptions, conversations and evidence; ordinary console-log redaction does not remove persisted content.
- Use SQLite's online backup API or stop all writers before taking a file backup. Copying only the main database file while WAL writes are active can omit committed data.
- Test restore into a separate directory and run integrity/schema checks before replacing an application database.
- Back up before a future schema change. Implement explicit versioned migrations; changing `CREATE TABLE IF NOT EXISTS` alone does not migrate existing tables.
- There is no automatic retention purge, tamper-evident ledger or per-user/tenant database authorization in this assignment. File access and service authentication are deployment boundaries; local CLI access is trusted.
- For horizontal scaling, move persistence to a shared transactional database, add appropriately owned/renewed distributed leases or queued jobs, and define idempotency and retry contracts before adding replicas.

The schema and transaction behavior should be verified with temporary-database integration tests, including restart persistence, invalid foreign keys, duplicate review conflict, same-session isolation and rollback. See [07-test-scenarios.md](07-test-scenarios.md) for acceptance cases and the final coverage document for executed evidence.
