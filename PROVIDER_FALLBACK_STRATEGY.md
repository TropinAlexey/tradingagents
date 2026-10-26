# TradingAgents — Provider-Agnostic Fallback Chains & Optimal Strategy

## Summary (2026-10-26)

Implemented **provider-agnostic fallback chains** for ALL providers (not just OpenRouter) and applied an optimal LLM strategy for multi-tier execution.

---

## Changes Made

### 1. New Config Keys (`tradingagents/default_config.py`)

```python
# Tier-level fallbacks (CSV or JSON list)
TRADINGAGENTS_QUICK_FALLBACK_MODELS      → quick_fallback_models
TRADINGAGENTS_DEEP_FALLBACK_MODELS       → deep_fallback_models

# Provider-specific overrides (JSON: {"provider": "model-a,model-b"})
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER → quick_fallback_by_provider
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER  → deep_fallback_by_provider
```

### 2. New Module: `tradingagents/llm_clients/fallback.py`

- **`FallbackChatModel`** — wraps primary + fallback models, retries on retryable errors (429, capacity, unavailable, model_not_found, etc.)
- **`create_fallback_chain()`** — factory to build chains
- **`_get_provider_fallbacks()`** — resolves fallback chain with priority:
  1. Provider-specific override (`*_by_provider` dict, iterates in order)
  2. Tier-level fallback (`*_fallback_models`)

### 3. All Clients Updated

| Client | File | Fallback Support |
|--------|------|------------------|
| OpenAI-compatible (OpenRouter, NVIDIA, xAI, DeepSeek, Qwen, GLM, MiniMax, Mistral, Groq, Ollama, custom) | `openai_client.py` | ✅ Native (OpenRouter) + client-side (others) |
| Anthropic | `anthropic_client.py` | ✅ Client-side |
| Google | `google_client.py` | ✅ Client-side |
| Azure | `azure_client.py` | ✅ Client-side |
| Bedrock | `bedrock_client.py` | ✅ Client-side |

### 4. Graph Integration (`tradingagents/graph/trading_graph.py`)

- `_fallback_models(config, tier, provider)` — now calls `_get_provider_fallbacks` with provider context
- Passes `fallback_model_names` to client kwargs

---

## Optimal Strategy Applied (Working Configuration)

### `.env` Configuration

```bash
# Quick tier (analysts/trader/risk) — OpenRouter + Anthropic Sonnet 5
# NVIDIA Nemotron doesn't support bind_tools() required by analysts
TRADINGAGENTS_QUICK_PROVIDER=openrouter
TRADINGAGENTS_QUICK_THINK_LLM=anthropic/claude-sonnet-5
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER={"openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6"}

# Deep tier (research/portfolio managers) — OpenRouter + Anthropic Opus 5.5
TRADINGAGENTS_DEEP_PROVIDER=openrouter
TRADINGAGENTS_DEEP_THINK_LLM=anthropic/claude-opus-5-5
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER={"openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6"}

TRADINGAGENTS_TEMPERATURE=0.1
```

### Rationale

| Tier | Primary | Fallback Chain | Why |
|------|---------|----------------|-----|
| Quick | OpenRouter: Sonnet 5 (tool-capable, fast) | OpenRouter: Gemini 3.8 Flash → DeepSeek Chat → Grok 4.6 | All support `bind_tools()`; different model families = diverse failure modes |
| Deep | OpenRouter: Opus 5.5 (best reasoning) | OpenRouter: Fable 5.1 → Gemini 3.1 Pro → Grok 4.6 | Different architectures = diverse failure modes |

### Key Insights

1. **NVIDIA Nemotron doesn't support `bind_tools()`** — required by all analysts (market, social, news, fundamentals). Must use tool-capable models.
2. **OpenRouter native fallback preserved** — uses `models` array in single request (no extra round-trips), capped at 3
3. **Client-side fallback for all other providers** — sequential retry on retryable errors
4. **Legacy `*_fallback_models` cleared** — replaced by provider-specific config
5. **Single API key for both tiers** — OpenRouter handles all models, simplifying key management

---

## Verification Results

```bash
# All tests pass
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped

# Ruff clean
$ .venv/bin/python -m ruff check .
All checks passed!

# Fallback chains verified
Quick fallbacks:  ['google/gemini-3.8-flash', 'deepseek/deepseek-chat', 'xai/grok-4.6']
Deep fallbacks:   ['anthropic/claude-fable-5-1', 'google/gemini-3.1-pro-preview', 'xai/grok-4.6']
```

---

## Files Modified

| File | Purpose |
|------|---------|
| `tradingagents/default_config.py` | New env overrides + defaults (ccxt_exchange, ccxt_market_type) |
| `tradingagents/llm_clients/fallback.py` | **New** — fallback wrapper & resolver |
| `tradingagents/llm_clients/factory.py` | Import `create_fallback_chain` |
| `tradingagents/llm_clients/openai_client.py` | Native OpenRouter + client-side fallback |
| `tradingagents/llm_clients/anthropic_client.py` | Client-side fallback |
| `tradingagents/llm_clients/google_client.py` | Client-side fallback |
| `tradingagents/llm_clients/azure_client.py` | Client-side fallback |
| `tradingagents/llm_clients/bedrock_client.py` | Client-side fallback |
| `tradingagents/llm_clients/__init__.py` | Export new symbols |
| `tradingagents/graph/trading_graph.py` | Pass fallback_model_names with provider context |
| `tradingagents/dataflows/router.py` | Auto-route crypto symbols to ccxt |
| `tradingagents/dataflows/vendors/ccxt/ohlcv.py` | **New** — ccxt OHLCV vendor (Binance/Bybit) |
| `tradingagents/dataflows/vendors/ccxt/__init__.py` | **New** — ccxt vendor package |
| `scripts/apply_optimal_strategy.py` | **New** — apply & verify strategy |

---

## Autoloop Demo Status

- ✅ Cycle runs without `NotImplementedError` (tool-capable models)
- ✅ Fallback chains work (OpenRouter native, capped at 3)
- ⚠️ Cycle takes 10+ minutes (OpenRouter latency, sequential LLM calls)
- ⚠️ Need to verify Binance Demo futures execution path end-to-end

---

# TODO: Reliable Profitable Crypto Hedge Fund

Based on the codebase analysis, here's the roadmap to a production-ready crypto hedge fund:

## Phase 1: Core Reliability (Weeks 1-2)

### 1.1 LLM Pipeline Hardening
- [ ] **Add request/response logging** for all LLM calls (audit trail)
- [ ] **Implement structured output validation** with retry on schema violation
- [ ] **Add token usage tracking** per agent/tier for cost monitoring
- [ ] **Circuit breaker** for OpenRouter: switch to fallback provider on sustained errors
- [ ] **Parallelize independent analysts** (market/social/news run concurrently)

### 1.2 Data Layer Robustness
- [x] **Add crypto-native OHLCV vendor** (Binance/Bybit via ccxt) — replace yfinance for crypto
  - yfinance fails on `BTC-USD` (quoteSummary endpoint doesn't support crypto)
  - Current: `crypto_universe` uses Binance but OHLCV falls back to yfinance
  - ✅ Implemented: `tradingagents/dataflows/vendors/ccxt/ohlcv.py` with Binance/Bybit support
  - ✅ Router auto-routes crypto symbols (BTC-USD, ETH-USD, etc.) to ccxt
  - ✅ Config: `ccxt_exchange` (binance/bybit), `ccxt_market_type` (spot/futures)
  - ✅ Default vendor chain: `core_stock_apis: "ccxt(binance),ccxt(bybit),yfinance"`
- [x] **Add Bybit as secondary venue** for price discovery (redundancy)
  - ✅ Vendor chain: `ccxt(binance),ccxt(bybit),yfinance`
  - ✅ Router tries Binance first, falls back to Bybit on rate limit/error
- [x] **Implement point-in-time data validation** — reject stale prices (>30 min)
  - ✅ Added `MAX_OHLCV_STALE_MINUTES = 30` in ccxt OHLCV vendor
  - ✅ Dual check: day-level (backtest) + minute-level (live runs)
  - ✅ Only applies when `curr_date == today` (live mode)
- [ ] **Add funding rate data** for futures basis analysis

### 1.3 Execution Safety
- [ ] **Dry-run mode validation** — simulate full cycle without live orders
- [ ] **Add pre-trade risk checks** in autoloop (position limits, daily loss)
- [ ] **Implement order idempotency keys** — prevent duplicate orders on retry
- [ ] **Add kill-switch integration** — halt all venues on risk breach

## Phase 2: Strategy Sophistication (Weeks 3-4)

### 2.1 Signal Quality
- [ ] **Add on-chain metrics** (whale flows, exchange reserves, stablecoin supply)
- [ ] **Implement regime detection** (trend/range/volatility) — adjust risk params
- [ ] **Add cross-asset correlation analysis** — BTC/ETH/SOL/altcoin basket
- [ ] **Funding rate arbitrage detector** — spot/futures basis trades

### 2.2 Portfolio Construction
- [ ] **Multi-asset position sizing** — Kelly criterion with drawdown constraints
- [ ] **Dynamic hedge ratio** — adjust futures hedge based on beta to BTC
- [ ] **Implement scale-in/scale-out logic** — tranche entries/exits
- [ ] **Add sector/thematic buckets** — DeFi, L1, AI, meme, etc.

### 2.3 Risk Management
- [ ] **VaR/ES monitoring** — real-time portfolio risk
- [ ] **Tail risk hedging** — OTM puts / variance swaps when available
- [ ] **Liquidity risk model** — order book depth analysis before sizing
- [ ] **Counterparty risk limits** — per-venue exposure caps

## Phase 3: Production Infrastructure (Weeks 5-6)

### 3.1 Observability
- [ ] **Structured logging** (JSON) for all components
- [ ] **Metrics dashboard** (Grafana/Prometheus): PnL, latency, error rates, token costs
- [ ] **Alerting** — PagerDuty/Slack on: daily loss > 2%, API errors > 5%, latency > 30s
- [ ] **Distributed tracing** — OpenTelemetry for LLM → execution pipeline

### 3.2 Deployment
- [ ] **Docker Compose for all services** (PostgreSQL, Redis, API, autoloop, web)
- [ ] **CI/CD pipeline** — test → staging → production with canary deploys
- [ ] **Secrets management** — Vault or AWS Secrets Manager
- [ ] **Disaster recovery** — automated DB backup/restore, RPO < 1hr

### 3.3 Compliance & Audit
- [ ] **Immutable audit log** — append-only, cryptographically signed
- [ ] **Regulatory reporting hooks** — Form PF, MiCA preparation
- [ ] **Investor reporting automation** — monthly tear sheets, attribution

## Phase 4: Alpha Generation (Ongoing)

### 4.1 Research Pipeline
- [ ] **Backtesting framework** — walk-forward, purged K-fold, transaction costs
- [ ] **Factor library** — momentum, mean reversion, carry, volatility
- [ ] **ML model registry** — versioned, reproducible, A/B testable
- [ ] **Alternative data integration** — satellite, credit card, web traffic

### 4.2 Strategy Diversification
- [ ] **Market neutral stat arb** — cross-exchange, cross-asset
- [ ] **Event-driven** — earnings, token unlocks, governance votes
- [ ] **Yield strategies** — staking, lending, basis trading
- [ ] **Options/volatility** — when Deribit/Paradex integration ready

## Immediate Next Steps (This Week)

1. **Fix crypto data vendor** — add Binance/Bybit OHLCV to router (replace yfinance for crypto)
2. **Reduce cycle time** — parallelize analysts, add response caching
3. **Run full dry-run** — 24h autoloop on Binance Demo, verify no live orders
4. **Load test** — 100 cycles simulation, measure latency/error rates
5. **Document runbook** — incident response, rollback procedures, key contacts

---

## Architecture Notes

### Fallback Flow

```
User Config (.env)
    ↓
DEFAULT_CONFIG (with _ENV_OVERRIDES)
    ↓
TradingAgentsGraph.__init__
    ↓
_tier_llm_settings() → quick_provider, deep_provider
    ↓
build_llm_kwargs() → kwargs including fallback_model_names
    ↓
create_llm_client(provider, model, **kwargs)
    ↓
Client.get_llm()
    ├─ OpenRouter: binds `extra_body={"models": [primary, fallback1, fallback2]}`
    └─ Others: returns FallbackChatModel(primary, [fallback1, fallback2])
```

### Provider Resolution

```python
# In _get_provider_fallbacks (fallback.py)
provider_fallbacks = {"openrouter": "model-a,model-b"}  # from env
# Iterates dict values in order, returns first non-empty
```

---

## Quick Reference Commands

```bash
# Apply strategy
.venv/bin/python scripts/apply_optimal_strategy.py

# Run single cycle (dry-run)
TRADINGAGENTS_EXEC_LIVE=false python -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from server.autoloop import _run_cycle
config = DEFAULT_CONFIG.copy()
ta = TradingAgentsGraph(config=config)
results = _run_cycle(lambda cfg, a: ta)
print(results)
"

# Run tests
.venv/bin/python -m pytest tests/ -q

# Lint
.venv/bin/python -m ruff check .
```