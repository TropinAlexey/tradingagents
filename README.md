<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>
<br>
<div align="center">
  <a href="https://github.com/TauricResearch" target="_blank"><img alt="TradingAgents #1 Repository of the Day" src="https://trendshift.io/api/badge/repositories/16192" width="250" height="55"/></a>
</div>
<br>
<div align="center">
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agent LLM Financial Trading Framework

## News

<!-- news:start -->
- **[2026-10] TradingAgents v0.6.0** — Phase 1 Core Reliability: provider-agnostic LLM fallback chains, crypto-native OHLCV via ccxt (Binance/Bybit), multi-venue fallback, point-in-time validation (30-min live / 10-day backtest), NVIDIA Nemotron/Gemma-4 support. Full release notes in [CHANGELOG.md](CHANGELOG.md).
- **[2026-09] TradingAgents v0.5.1** — package layout organized by module (import paths moved), optional Jev screening of social posts, GPT-6 Sol/Luna as default models, fixes to run isolation and SEC EDGAR statements.
- **[2026-09] TradingAgents v0.5.0** — point-in-time integrity across every dated path, SEC EDGAR fundamentals served as filed, backtesting over ticker/date grid, portfolio-aware runs, current model lineups across every provider.
- **[2026-08] TradingAgents v0.4.0** — point-in-time fixes across FRED macro, social sentiment, decision-log memory; clearer decision signals; working CLI checkpoint resume; Trader price grounding; GPT-5.6 and GLM-5.3 models.
<!-- news:end -->

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | 🛡️ [Risk Management](#risk-management) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

---

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

---

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents — fundamental analysts, sentiment experts, technical analysts, trader, risk management team — the platform collaboratively evaluates market conditions and informs trading decisions. Agents engage in structured debates to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> ⚠️ TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

### Analyst Team
- **Fundamentals Analyst** — Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- **Sentiment Analyst** — Aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read to gauge short-term market mood.
- **News Analyst** — Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- **Technical Analyst** — Utilizes technical indicators (MACD, RSI, etc.) to detect trading patterns and forecast price movements.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- **Bull Researcher** & **Bear Researcher** — Critically assess insights from the Analyst Team through structured debates, balancing potential gains against inherent risks.
- **Research Manager** — Synthesizes the debate into a consolidated research report.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from analysts and researchers to make informed trading decisions, determining timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management & Portfolio Manager
- **Risk Analysts** (Aggressive / Conservative / Neutral) — Evaluate portfolio risk from different perspectives.
- **Portfolio Manager** — Approves/rejects the transaction proposal. If approved, the order is sent to the exchange bridge and executed.
- Execution-time safety controls — halt, daily loss, slippage guard, emergency close — are described in [Risk Management](#risk-management).

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

---

## Phase 1: Core Reliability (v0.6.0+)

TradingAgents v0.6.0 introduces Phase 1 hardening across the entire pipeline:

### Provider-Agnostic LLM Fallback Chains
- **Cross-provider fallbacks** — any provider (OpenRouter, NVIDIA, Anthropic, Google, xAI, DeepSeek, etc.) can have fallback models via `TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER` / `TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER`
- **OpenRouter native fallback** — uses `models` array in single request (no extra round-trips), capped at 3
- **Client-side fallback** — sequential retry on 429/capacity/unavailable errors for all other providers
- **Per-tier configuration** — quick tier (analysts/trader/risk) and deep tier (managers) use different providers with independent fallback chains

### Crypto-Native Data Layer
- **ccxt OHLCV vendor** — Binance + Bybit support for spot/futures (`tradingagents/dataflows/vendors/ccxt/ohlcv.py`)
- **Auto-routing** — crypto symbols (`BTC-USD`, `ETH-USD`, `SOL-USD` + 100+) automatically route to ccxt
- **Multi-venue fallback** — vendor chain: `ccxt(binance),ccxt(bybit),yfinance`
- **Point-in-time validation** — dual stale check: day-level (backtest) + minute-level (live runs, 30 min max staleness)
- **Configurable exchange** — `ccxt_exchange` (binance/bybit), `ccxt_market_type` (spot/futures)

### Configuration via Environment
```bash
# Quick tier (analysts/trader/risk)
TRADINGAGENTS_QUICK_PROVIDER=openrouter
TRADINGAGENTS_QUICK_THINK_LLM=anthropic/claude-sonnet-5
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER={"openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"}

# Deep tier (managers)
TRADINGAGENTS_DEEP_PROVIDER=openrouter
TRADINGAGENTS_DEEP_THINK_LLM=anthropic/claude-opus-5-5
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER={"openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it"}

# Crypto data
TRADINGAGENTS_CORE_STOCK_APIS="ccxt(binance),ccxt(bybit),yfinance"
TRADINGAGENTS_CCXT_EXCHANGE=binance
TRADINGAGENTS_CCXT_MARKET_TYPE=spot
```

---

## Risk Management

TradingAgents ships execution-time risk controls that live next to the exchange bridge and use a shared, append-only `audit.jsonl` as their source of truth. The checks run when a plan is created and again immediately before any order is sent, so a halt appended by another process, the web API, or a human operator always blocks the next live trade.

### Halt / Kill Switch
A halt is a single sticky line in `audit.jsonl`. Once written, every subsequent order is refused until `reset_halt()` is called or a matching `halt_reset` line is appended. Halts do **not** self-expire at UTC midnight. Append one manually, via the server API, or from any process that writes to the same log.

### Daily Loss Limit
The daily loss figure combines:
- realized P&L from trades closed today, and
- unrealized P&L on every open lot, marked to the current market price.

This prevents a position opened earlier from silently drifting past the loss limit. Realized trades before the most recent `halt`/`halt_reset` are excluded, so a forgiven breach cannot re-fire the halt.

### Execution-Price P&L and Fees
When an order fills, the bridge records the actual execution price (`price_exec`) and the venue's quote-equivalent fee (`fee`) in `audit.jsonl`. The FIFO P&L replay uses the fill price and subtracts the pro-rata fee for each matched lot, so reported P&L matches what the exchange actually charged.

### Fail-Closed Execute Checks
Plan-time checks stay fail-open so rehearsal plans without a portfolio are not falsely rejected. At execute time the check is fail-closed:
- an unreadable or corrupt `audit.jsonl` refuses the order,
- a missing computable equity refuses the order in live mode,
- an active halt refuses the order.

### Slippage Guard
Set `exec_max_slippage_pct` (or `TRADINGAGENTS_EXEC_MAX_SLIPPAGE_PCT`) to reject a market order when the fresh price deviates from the planned price by more than the configured fraction. `0.0` disables the guard and keeps unconditional market orders.

### Emergency Close
If a spot entry fills but the exchange-side protective bracket (stop-loss / take-profit) cannot be placed, the bridge immediately sends an emergency market-sell to close the position. The position is never left unprotected until the next cycle.

### Risk Configuration

| Key | Env Variable | Default | Meaning |
|-----|--------------|---------|---------|
| `risk_max_daily_loss_pct` | `TRADINGAGENTS_RISK_MAX_DAILY_LOSS_PCT` | `5.0` | Maximum allowed daily loss as % of equity |
| `risk_max_consecutive_loss_count` | `TRADINGAGENTS_RISK_MAX_CONSECUTIVE_LOSS_COUNT` | `3` | Consecutive losing days before halt triggers |
| `risk_max_position_pct_per_asset` | `TRADINGAGENTS_RISK_MAX_POSITION_PCT_PER_ASSET` | `25.0` | Max position size per asset as % of equity |
| `risk_max_total_exposure_pct` | `TRADINGAGENTS_RISK_MAX_TOTAL_EXPOSURE_PCT` | `80.0` | Max total exposure across all positions |
| `exec_max_slippage_pct` | `TRADINGAGENTS_EXEC_MAX_SLIPPAGE_PCT` | `0.0` | Max deviation from planned price; `0.0` = disabled |
| `exec_log_path` | `TRADINGAGENTS_EXEC_LOG_PATH` | `~/.tradingagents/execution/audit.jsonl` | Shared audit log path |

See `tradingagents/default_config.py` for the full list of risk and execution options.

---

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment:
```bash
# conda
conda create -n tradingagents python=3.12
conda activate tradingagents

# or uv (recommended)
uv venv --python 3.12
source .venv/bin/activate
```

Install the package and its dependencies:
```bash
pip install .
# or with uv
uv pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

After updating the repository, rebuild the image with `docker compose build`.

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen — International (dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen — China (dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax — Global (api.minimax.io)
export MINIMAX_CN_API_KEY=...      # MiniMax — China (api.minimaxi.com)
export OPENROUTER_API_KEY=...      # OpenRouter
export MISTRAL_API_KEY=...         # Mistral
export MOONSHOT_API_KEY=...        # Kimi (Moonshot)
export GROQ_API_KEY=...            # Groq
export NVIDIA_API_KEY=...          # NVIDIA NIM
export FRED_API_KEY=...            # FRED macro data (free, optional)
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
export TYPESAFE_API_KEY=...        # Jev social-post screening (optional)
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials (environment variables, `~/.aws/credentials`, or an IAM role) and `AWS_DEFAULT_REGION`, and use a Bedrock model ID, e.g. `us.anthropic.claude-opus-4-8-v1:0`.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`), e.g. `http://localhost:8000/v1` for vLLM or `http://localhost:1234/v1` for LM Studio. The model is whatever your server serves. No key is needed for local servers; set `OPENAI_COMPATIBLE_API_KEY` when the endpoint requires one.

With `TYPESAFE_API_KEY` set, the Sentiment Analyst screens StockTwits and Reddit posts with TypeSafe's Jev before reading them. Posts that are not about the company are dropped, and each source opens with a count of the remaining posts by stance: bullish, bearish, neutral, or unclear. Without the key, posts pass through unscreened. `jev-latest` moves with new releases; set `TYPESAFE_DEFAULT_MODEL` to a versioned ID such as `jev-1.13.0` to hold it fixed across runs.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

Launch the interactive CLI:
```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more. Your previous run's answers come back as the defaults, so pressing Enter accepts them. The `TRADINGAGENTS_*` variables in `.env` still skip their step entirely.

### Markets and Tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS`, Shenzhen `.SZ` (e.g. `600519.SS` for Kweichow Moutai)
- Crypto: `BTC-USD`, `ETH-USD`

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

---

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openrouter"      # openrouter, anthropic, google, deepseek, groq, ollama, nvidia, openai_compatible, etc.
config["deep_think_llm"] = "anthropic/claude-opus-5-5"    # Model for complex reasoning
config["quick_think_llm"] = "anthropic/claude-sonnet-5"   # Model for quick tasks
config["max_debate_rounds"] = 2
config["max_risk_discuss_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)
```

See `tradingagents/default_config.py` for all configuration options.

### Fundamentals as Filed (SEC EDGAR)

US company statements can come from SEC EDGAR, which records the date every figure was filed. A run dated in the past then reads the statements exactly as they stood that day: a fiscal year that has ended but has not been filed yet is not served, and a figure restated later still reads as first reported. Apple's 2008 total assets were filed as $39.6B and restated to $36.2B in 2010, so a run dated in between reads $39.6B.

EDGAR needs no account or API key. Add the vendor to the chain:
```python
config["data_vendors"]["fundamental_data"] = "sec_edgar,yfinance"
```

SEC asks callers to identify themselves and refuses requests that carry no contact address, so a default one is sent. Set your own so SEC can reach you rather than the project:
```bash
SEC_EDGAR_USER_AGENT="Your Name your@email.com"
```

It covers companies that file with the SEC, including foreign companies listed in the US. Anything else, such as Hong Kong or A-share listings, falls through to the next vendor in the chain. EDGAR's machine-readable filings begin in 2009, and a fourth quarter is reported as unavailable rather than derived, because filers publish it only inside the annual figure.

### Current Holdings

By default the agents do not know what you hold, so their guidance is written for a reader who applies it to their own position. Pass a portfolio to have the trader, the risk analysts and the portfolio manager work against your actual book.

```python
from tradingagents.portfolio import PortfolioContext

portfolio = PortfolioContext.model_validate({
    "cash": 25000.0,
    "currency": "USD",
    "positions": [{"ticker": "NVDA", "quantity": 120, "average_price": 150.0}],
})
_, decision = ta.propagate("NVDA", "2026-09-01", portfolio=portfolio)
```

The CLI takes the same content as a JSON file: `tradingagents --portfolio my_book.json`.

An empty `positions` list means a flat book, which is different from passing nothing. A run without a portfolio is never treated as flat.

---

## Persistence and Recovery

### Decision Log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw, and alpha against the instrument's regional benchmark), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint Resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. The run view says whether it resumed a saved run or started fresh. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents --checkpoint           # enable for this run
tradingagents --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
```

---

## Evaluating Decisions Over Time

One run gives one decision, which cannot tell you whether the system decides well. `run_backtest` runs the same pipeline over a grid of tickers and dates, writes to a decision log of its own, and scores the decisions whose holding window has since traded.

```python
from tradingagents.backtest import iter_grid, run_backtest, summarize

dates = iter_grid("2026-06-01", "2026-08-01", every_n_days=7)
result = run_backtest(["NVDA", "AAPL"], dates, config, selected_analysts=["market", "news"])
print(summarize(result).render())
```

From the CLI:
```bash
tradingagents backtest NVDA,AAPL --start 2026-06-01 --end 2026-08-01 --every 7
```

Each cell is scored on realized alpha against the instrument's regional benchmark, grouped by rating. Your own decision log is never written to, and re-running the same grid with `run_id=result.run_id` skips the cells that already ran, so an interrupted sweep continues where it stopped.

---

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

- **Language model sampling** is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-6 family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.
- **Live data moves**. News, StockTwits, and Reddit return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. The current curated models are reasoning-first and largely ignore temperature, so for tighter reproducibility name a non-reasoning model in your config, or in `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM`. Any model ID your provider serves is accepted, whether or not the picker lists it.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openrouter"
config["temperature"] = 0.0
# Reasoning models ignore temperature. For tighter reproducibility, name a
# non-reasoning model in deep_think_llm / quick_think_llm.
```

What does not vary anymore: the analyzed company identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot. Earlier reports of "different companies" or fabricated price levels across runs are addressed by these two mechanisms.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return.

---

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

---

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```