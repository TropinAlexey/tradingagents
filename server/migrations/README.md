# PostgreSQL migrations

`0001_core_ledger.sql` is an explicit, additive baseline schema for an isolated
PostgreSQL environment. Run `python -m server.postgres --dry-run` to list the
migration plan without opening a connection, or `python -m server.postgres` to
apply pending files from `TRADINGAGENTS_DATABASE_URL`. The runner owns the
canonical `schema_migrations` ledger, records each file name and SHA-256
checksum, and serializes runs with a PostgreSQL advisory lock inside its
transaction. Migration files contain schema DDL only; do not add a separate
ledger row or explicit transaction wrapper.

The runner IS wired to application startup: `server/main.py:_open_state_db()`
calls `postgres.migrate()` before the API serves a request, and the control
plane has no SQLite fallback (`server/db.py`). PostgreSQL holds jobs, runs,
approvals, settings, the watchlist and durable position state. The execution
audit log (`exec_log_path`) stays JSONL because it is the cross-process replay
contract for RiskGuard, not control-plane state. Applying this schema is not
permission to enable execution: the execution gates remain independent.

## Ledger invariants

- Workspace ownership is carried through composite foreign keys on jobs, runs,
  decisions, approvals, orders, fills, context links, and position snapshots.
- Parent deletion does not cascade into analysis or financial history.
- One job result is permitted per `(workspace, job, instrument, attempt)`. A
  retry is a new attempt and gets a new attempt number.
- Approval references, when present, must identify a result/run or a
  decision/run/instrument tuple consistently. `claim_approval` is a conditional
  update and yields a row to at most one concurrent worker.
- Before any venue request, the caller must claim the approval and insert the
  execution order in the same short database transaction. Commit before
  network I/O. Persist a timeout as `submission_unknown`; reconcile by account
  and client ID before any retry. No exactly-once guarantee is claimed across
  the database/venue boundary.
- `client_order_key` is the lowercase SHA-256 hex digest of a canonical intent
  scoped by workspace, account, approval, and intent version. The venue-facing
  ID is `ta_` plus the first 32 hex characters (35 ASCII characters total).
- Event idempotency keys and fill trade IDs are unique per account. Replayed
  duplicates therefore fail the uniqueness constraint instead of duplicating
  evidence.

## Integration verification

Run `.venv/bin/python -m pytest -q tests/test_postgres_migrations_integration.py`
(`.venv\Scripts\python.exe` on Windows). The test starts a PostgreSQL 16 service
using the isolated `tests/postgres-compose.yml` project, then removes only its
uniquely named Compose project and volume. It skips when Docker Engine is
unavailable.
