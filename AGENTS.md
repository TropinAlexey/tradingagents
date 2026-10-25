---
purpose: Project rules for AI agents
updated: 2026-10-25
source: generated-by-zcode-starterkit
---

# AGENTS.md

## Purpose

TradingAgents — a multi-agent LLM financial trading framework (research tool): LangGraph-orchestrated analyst/researcher/trader/risk agents over market data vendors, shipped as a Python library + Typer CLI.

## Source of Truth

1. This `AGENTS.md`
2. Repo-local docs (`README.md`, `CHANGELOG.md`, `.env.example`, `pyproject.toml` comments)
3. `.zcode/memory/project/tech-stack.md`
4. Code and tests
5. Baseline / external catalogs only when they match this repo's stack or surface

## Stack Snapshot

- **Language:** Python ≥ 3.10 (CI matrix: 3.10–3.13; local venv runs 3.13)
- **Framework:** LangGraph + LangChain provider clients; Typer/Rich CLI
- **Package Manager:** pip, setuptools backend, no lockfile (`pip install -e ".[dev]"`)
- **Detected Shape:** Python library + CLI (`tradingagents = cli.main:app`), Docker optional

## Core Coding Contract

- Read repo instructions, docs, configs, and nearby code before editing.
- Prefer existing patterns and the smallest correct diff.
- Preserve current public APIs, data shapes, and external side effects only when they are part of the current requirements; do not add backward-compatibility layers, migrations, or fallbacks for obsolete behavior.
- Do not add dependencies, frameworks, broad refactors, or generated churn unless the task requires them.
- Run the repo's actual relevant commands after meaningful changes: `.venv\Scripts\python.exe -m ruff check .` and `.venv\Scripts\python.exe -m pytest -q` (see Verified Commands).
- Self-review the diff, including untracked files, and remove debug leftovers before completion.
- Report skipped verification with reasons instead of claiming unverified success.

## Engineering Principles

1. Do not preserve backward compatibility. Delete obsolete code directly; do not add compatibility layers, write migrations, or leave fallbacks.
2. Choose the simplest implementation that satisfies the current requirements. Avoid speculative abstractions and unnecessary configuration layers.
3. Keep the system layered for the long term. First make a minimal end-to-end version work, then add complexity. Never dismantle working code for unfinished complexity.
4. Keep components modular and separate concerns.
5. Prefer mature, actively maintained libraries. Do not rewrite established capabilities without a clear reason.
6. Inspect what existing dependencies can already do before adding packages or writing custom code. Do not assume a library is unavailable.
7. Make architecture decisions for the long term. Do not accept temporary solutions framed as "we can replace this later."
8. First study how mature products solve the same problem and use proven patterns; do not invent from scratch.

## Coding Standards (apply strictly)

- **Source:** LLM Wiki cross-language cookbook (`C:\Users\mrc\Documents\projects\agent-wiki`) + Python deep cookbook. Reopen via the `obsidian` skill for detail.

### Shared rules across languages
- Prefer the repo's own conventions over generic style guidance.
- Use the ecosystem's canonical formatter first, then linter, then tests. Here: `ruff check` (formatter NOT yet adopted repo-wide — do not run `ruff format` on the whole repo).
- Keep the smallest possible diff that satisfies the requested behavior.
- Match naming, file layout, import/order conventions, and module boundaries already used in the repo.
- Do not invent abstractions, helpers, or architecture unless the repo requires them.
- Preserve public APIs and behavior unless a breaking change is explicitly approved.
- Add or update tests for every behavior change.
- Keep comments factual and sparse.
- Treat errors, edge cases, and validation as part of the standard, not an afterthought.
- Verify before finalizing: linting, tests (and type checks when applicable).

### Structural rules common to all languages (mandatory)
- **One file = one responsibility.** A file is one module named after a single concern; if the name needs "and"/"or" to be honest, it has too many. Cohesion wins over colocation by type.
- **Split signals (any one fires a mandatory split proposal):**
  1. Multi-role identity — the file answers more than one "what does this do?" question.
  2. Section-header navigation — you scroll past unrelated sections to reach your change.
  3. Unrelated pile-up — new code is unrelated to the file's primary concern.
  4. Cross-domain import surface — imports from many unrelated subsystems.
  5. Repeated edits in different places by unrelated tasks.
  6. God symbol — one class/function/file handles multiple input domains or output shapes.
- Split at the responsibility seam, not a line count. A 200-line file serving two domains needs splitting; a 1500-line single-concern file may be fine.
- **Anti-patterns to refuse on sight:** `utils`/`helpers`/`common`/`misc` catch-all modules; grab-bag public surface; giant regression test files instead of mirroring the source split; "just one more function" on a module already showing split signals.
- **Repo-first override:** the repo's existing module-boundary convention wins over heuristics. This repo groups by what modules hold: `tradingagents/{agents, dataflows, graph, llm_clients}` + `cli/` + `tests/`.

### Escalation covenant (mandatory agent behavior)
Before finalizing any coding pass, scan the structure of every file the diff touches. If any split signal fires:
1. Surface a split proposal in the same turn, naming the proposed seam.
2. Pause for the user to decide. Do not silently refactor someone else's repo, and do not silently leave a violation either.
3. If declined, record `# ai-note: split declined because <reason>; revisit when signal X strengthens` at the file head.
4. If approved, perform the split in the same pass when practical, run lint/tests, and report the new boundaries.

### Python-specific (from the deep cookbook; repo wins on conflicts)
- No bare `except:`; catch specific types; chain with `raise NewError(...) from exc` when translating (see `_apply_env_overrides`).
- Imports at top, grouped stdlib → third-party → local; absolute imports; ruff `I` enforces order.
- Modules stay importable with no side effects; guard `main()`/CLI entrypoints.
- Naming: `lower_with_under` functions/modules, `CapWords` classes, `CAPS_WITH_UNDER` constants, `Error` suffix on real exceptions.

## Selected Guideline Packs

- **Primary (strong):** LLM Wiki `queries/coding-standards-cross-language-cookbook.md` + `queries/coding-standards-programming-languages-python-cookbook.md` (vault: `C:\Users\mrc\Documents\projects\agent-wiki`).
- **Secondary:** bundled `agent-skills-standard` (pinned `9f695e8`, 2026-08-01) file-matched packs: `python/python-language`, `python/python-tooling`, `python/python-testing`, `python/python-architecture`.
- **Ignored:** TypeScript/JavaScript/frontend/mobile/database packs (no such surfaces in this repo).

## Stack-Specific Rules

- Tests use pytest markers `unit` / `integration` / `smoke` (`--strict-markers`); new markers must be registered in `pyproject.toml`. Unit tests must not hit the network — mock vendors/LLMs; live-API tests skip themselves when keys are absent.
- CI also runs the suite under `TZ=America/New_York`: never write timezone-dependent assertions; resolve dates with explicit `zoneinfo`/`pytz` zones.
- Always pass `encoding="utf-8"` when opening text files (Windows default is cp1252; this project fixed UTF-8 bugs before).
- New env-overridable config keys go in `_ENV_OVERRIDES` in `tradingagents/default_config.py` — coercion follows the default's type; no entry-point changes needed.
- Never introduce look-ahead in dated data paths: a run dated in the past must read data as it stood that day (point-in-time integrity is a core v0.5 contract).
- Check Python version compat: code must run on 3.10–3.13, so no 3.11+-only syntax in `tradingagents/`.

## Repo-Specific Rules

- Import paths moved in v0.5.1: modules are grouped by what they hold (`agents/`, `dataflows/`, `graph/`, `llm_clients/`). Check `tradingagents/__init__.py` / existing imports before adding new ones.
- `ruff check .` must stay clean; the repo deliberately ignores `E501` and defers repo-wide `ruff format` — do not mass-reformat.
- Vendor/data-vendor chains (`data_vendors` config) fall through in order; keep the fallback chain contract when touching dataflows.
- The CLI entry is `cli/main.py` (Typer); user-facing state lives under `~/.tradingagents/` (logs, cache, memory log, checkpoints) — never write run state into the repo.
- `results/` is generated output, excluded from ruff; don't edit or commit it.

## Execution Risk Management

The execution bridge and risk guard share a single append-only `audit.jsonl` under `exec_log_path` (default `~/.tradingagents/execution/audit.jsonl`). Treat it as the cross-process source of truth for halt state, P&L replay, and consecutive-loss counting.

- **Halts are sticky.** A `halt` event blocks every subsequent order until a matching `halt_reset` event is appended or `reset_halt()` is called. Halts do **not** self-expire at UTC midnight. Use `_halted(events)` (not `_halted_today`) when reading state; `server/audit.py` and `server/portfolio.py` were migrated to `_halted`.
- **Daily loss includes unrealized P&L.** `_daily_pnl` counts realized P&L from today's closed trades plus unrealized P&L on **all** open lots, marked to the current price. Only realized trades at or before the forgiveness point (latest halt/halt_reset) are excluded.
- **P&L uses execution price and fees.** Fills must record `price_exec` and `fee` in the audit event. `_replay` matches lots FIFO and subtracts pro-rata fees from realized P&L.
- **Fail-closed at execute time.** `RiskGuard.check(..., fail_closed=True)` (used for live sends in `bridge.py`) refuses the order when the audit log is unreadable, contains corrupt lines, equity is not computable, or a halt is active. Plan-time checks remain fail-open so rehearsals without a portfolio are not falsely rejected.
- **Slippage guard.** `exec_max_slippage_pct` rejects a market order when the fresh price deviates from the planned price by more than the configured fraction. `0.0` disables the guard.
- **Emergency close.** If a spot buy fills but the exchange-side stop-loss/take-profit bracket cannot be placed, `bridge.py` immediately market-sells the position. Never leave a spot entry unprotected.
- **Audit durability.** `append_event` flushes and fsyncs the audit log before returning.
- **Env overrides.** New execution/risk config keys must be added to `_ENV_OVERRIDES` in `tradingagents/default_config.py` to be overridable from the environment.

## Boundaries / Gotchas

- API keys come from env / `.env` only (see `.env.example`); never commit keys or hardcode endpoints.
- `.venv/` is local (already gitignored); use `.venv\Scripts\python.exe` on Windows rather than global Python.
- LLM behavior is non-deterministic; tests assert structure/config plumbing, not model output.
- This is a research framework — not financial advice; keep disclaimers intact in user-facing output.

## Verified Commands

```bash
.venv\Scripts\python.exe -m pip install -e ".[dev]"   # fresh env setup
.venv\Scripts\python.exe -m ruff check .               # lint (strict select, full repo)
.venv\Scripts\python.exe -m pytest -q                  # full suite (1001 passed, 5 skipped on Windows 2026-09-28)
.venv\Scripts\python.exe -c "import tradingagents, cli.main"   # clean-import smoke (mirrors CI)
tradingagents --help                                   # CLI (installed entry point)
```

## Code Example

```python
# tradingagents/default_config.py — the env-var → config-key mapping is a table.
# To expose a config key, add a row here; coercion follows the existing default's type.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER": "llm_provider",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "max_debate_rounds",
    ...
}

def _apply_env_overrides(config: dict) -> dict:
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config
```

## Synthesis Notes

- **Rule translation:** wiki cross-language structural rules + Python cookbook error/import rules were folded into Coding Standards and Stack-Specific Rules; CI (`ci.yml`) supplied the verified command set and the TZ matrix gotcha; `pyproject.toml` comments supplied the "no repo-wide ruff format" rule.
- **Source notes:**
  - Local wiki (vault `C:\Users\mrc\Documents\projects\agent-wiki`): `queries/coding-standards-cross-language-cookbook.md` (Structural rules / Escalation covenant / Shared rules), `queries/coding-standards-programming-languages-cookbook.md`, `queries/coding-standards-programming-languages-python-cookbook.md`. Reopen via the `obsidian` skill (`read_note` / `search_notes`).
  - Bundled catalog: `agent-skills-standard` pinned commit `9f695e8e2c3e423dfcd420a0e6b80e0e99044088` (snapshot 2026-08-01, Apache-2.0) — packs listed under Selected Guideline Packs.
- **Open questions:** none blocking; `/review-codebase` can deepen subsystem notes.

## Research / investigation log

### 2026-10-25 — test fixes, two-axis review, and demo-cycle preparation

**Goal:** bring the repo to a green state after PR #12, perform a Standards + Spec review of all uncommitted/committed changes since `1b77064`, fix every review finding, then run dry and demo trading cycles.

**Fixes applied**
- Reverted shipped execution gates (`exec_live`, `exec_auto_confirm`, `exec_derivatives`) to `False` to keep the default fail-closed contract.
- `tradingagents/execution/bridge.py`:
  - `_binance_profile` made public; `_extract_fee` now converts base-asset fees to quote using the fill price.
  - Emergency close uses the actual held quantity (`bracket_qty`), not the planned quantity.
  - Added public `venue_key` / `bridge_venue_key` helpers.
  - Extended `audit_plan` signature with `price_exec` and `fee`.
- `tradingagents/execution/derivatives.py`: added fresh-price slippage guard on the live futures path before `create_order`.
- `server/autoloop.py`: futures universe now returns `[]` when production volume ranking fails (fail-closed) instead of falling back to synthetic demo volumes.
- `server/venue.py` (new), `server/control_store.py`, `server/main.py`: venue switch API wired; error code for invalid venue changed from `422` to `400`.
- `server/operator_config.py` + callers: exposed `ALLOWED_KEYS`; replaced private `_ALLOWED` imports.
- `tradingagents/execution/futures_account.py`: replaced silent `except: pass` with logged `Exception` catch.
- Unified duplicated `_venue_key` copies across `brackets.py`, `futures_protection.py`, `futures_adoption.py`.
- Updated `tradingagents/dataflows/screening.py` to use public `binance_profile`.
- Docs updated: `docs/ui-api-contract.md` §16 venue API, `docs/operator-guide.md` venue switch procedure, `server/migrations/README.md` PostgreSQL wiring.
- Added/updated tests for fee conversion, emergency-close quantity, derivatives slippage, and futures-universe fail-closed behavior.

**Verification**
```bash
.venv/bin/python -m ruff check .                              # clean
TRADINGAGENTS_TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest -q
# 1636 passed, 2 skipped, 91 subtests passed
```

**Dry test cycle (deterministic stub graph)**
- Started disposable PostgreSQL from `tests/postgres-compose.yml`.
- Ran `autoloop._run_cycle()` with a stub graph returning `Buy`, `exec_auto_confirm=True`, `exec_live=False`, temporary audit log.
- Result: `BTC-USD executed=True side=buy qty≈0.015486 price_est≈80719.06 mode=dry`.
- Audit contained plan + execute lines with stop-loss/take-profit; reason `dry-run: order not sent to exchange`.

**Full demo-cycle preparation**
- Verified `.env` provides `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_SECRET`, `OPENROUTER_API_KEY`, and `TRADINGAGENTS_LLM_PROVIDER=openrouter`.
- Default LLM models: `quick_think_llm = nvidia/nemotron-3-ultra-550b-a55b:free`, `deep_think_llm = anthropic/claude-sonnet-5.5`.
- To keep the demo run bounded, the script caps `AUTO_UNIVERSE_PER_ASSET=5` and `AUTO_SCREEN_POOL=3` in-process only.
- Required env flags for live demo execution: `TRADINGAGENTS_EXEC_LIVE=true` and `TRADINGAGENTS_EXEC_AUTO_CONFIRM=true`.
- Config literals armed via `PUT /api/operator-config`: `exec_live=true`, `exec_auto_confirm=true`; `exec_derivatives=false` (spot demo only).

**Spot demo-cycle result (Binance Demo Trading + OpenRouter LLM)**
- Started disposable PostgreSQL, migrated, then launched the control-plane server via `TestClient` with live env flags.
- Capped universe in-process to `AUTO_UNIVERSE_PER_ASSET=3` / `AUTO_SCREEN_POOL=1` to keep the run bounded.
- Initial `PUT /api/operator-config` without `confirm=true` returned `412 gate_confirmation_required`; retry with `confirm=true` + `reason` succeeded.
- `POST /api/autoloop/run-now` returned `202 started`.
- The cycle completed in ~10 minutes. The only screened candidate was `ETH-USD`; the real agent graph returned `Underweight`.
- Because the demo spot portfolio had no ETH position, the planner refused the order:
  - Audit: `ETH-USD signal=Underweight action=no_order reason="no position to close/reduce" price_est=2356.02 mode=dry`.
  - No order was sent to Binance Demo; no bracket was placed.
- Telemetry showed `graph_analysis` took ~613 s (real LLM calls via OpenRouter), `portfolio_sync` ~6 s, planning <1 s.
- Universe fetched: 3 crypto, 3 stock.

**Futures demo-cycle result (Binance Demo Futures + OpenRouter LLM)**
- Same setup, but armed all three gates: `exec_live=true`, `exec_auto_confirm=true`, `exec_derivatives=true`; env flags `TRADINGAGENTS_EXEC_LIVE=true`, `TRADINGAGENTS_EXEC_AUTO_CONFIRM=true`, `TRADINGAGENTS_EXEC_DERIVATIVES=true`.
- Venue confirmed demo; demo futures credentials present.
- `POST /api/autoloop/run-now` returned `202 started`.
- The cycle completed in ~4 minutes. Futures universe fetched 40 crypto contracts (settle assets `USDC`, `USDT`); screened candidate was `XMR-USD`.
- The real agent graph returned `Hold` with reason `agent_abstained`.
- Audit was empty; no futures order was sent to Binance Demo.
- Telemetry showed `graph_analysis` took ~206 s; several `OpenAIRateLimitError` occurred and were handled by falling back to report-only free text.
- **Post-run fix:** futures universe construction was changed from "most liquid contract per base asset" to "most liquid contract per settle asset held in the futures wallet, with no duplicate base assets". The screen score is now overridden to preserve this liquidity/settle order. This means a wallet holding both `USDT` and `USDC` will now analyze up to two distinct candidates (e.g. `BTC-USDT` and `SOL-USDC`) instead of a single momentum winner.

**System launcher**
- Added `start.sh` (macOS/Linux equivalent of `start.bat`).
- It checks `.venv/bin/python`, installs `web/node_modules` if missing, starts `uvicorn server.main:app` on port 8000, starts `npm run dev` in `web/` on port 3000, polls `/api/health`, then opens `http://localhost:3000`.
- Logs are written to `backend.log` and `frontend.log`; PIDs to `backend.pid` / `frontend.pid`.
