# SPEC: Crypto-Native OHLCV Data Layer (ccxt Vendor)

## Summary
Replaced yfinance for crypto OHLCV data with native ccxt-based vendor supporting Binance and Bybit (spot/futures), with auto-routing, multi-venue fallback, and point-in-time validation.

## Problem
yfinance fails on crypto symbols (`BTC-USD`, `ETH-USD`, etc.) because Yahoo's `quoteSummary` endpoint doesn't support crypto. The crypto universe used Binance for screening but fell back to yfinance for OHLCV, causing failures and stale data.

## Solution
Built a complete ccxt-based OHLCV vendor with multi-venue support and point-in-time guarantees.

### Architecture

#### 1. New Vendor Module
`tradingagents/dataflows/vendors/ccxt/ohlcv.py`:
- Supports Binance and Bybit (spot + futures)
- Rate limiting per exchange (Binance: 1200ms, Bybit: 100ms)
- Caching per symbol + exchange + market type (2-year history)
- Symbol mapping: `BTC-USD` → `BTC/USDT` (spot) or `BTC/USDT:USDT` (futures)

#### 2. Router Integration (`tradingagents/dataflows/router.py`)
- **Auto-routing**: 100+ known crypto bases (`BTC`, `ETH`, `SOL`, etc.) auto-route to ccxt
- **Vendor chain**: `ccxt(binance),ccxt(bybit),yfinance` — ordered fallback
- **Config-driven**: Reads `ccxt_exchange` and `ccxt_market_type` from config

#### 3. Point-in-Time Validation
Dual stale check in `_assert_ohlcv_not_stale()`:
1. **Day-level** (backtest safety): Latest row ≤ `MAX_OHLCV_STALE_DAYS` (10) vs `curr_date`
2. **Minute-level** (live safety): Latest row ≤ `MAX_OHLCV_STALE_MINUTES` (30) vs `now` — ONLY when `curr_date == today`

#### 4. Configuration (`tradingagents/default_config.py`)
```python
"data_vendors": {
    "core_stock_apis": "ccxt(binance),ccxt(bybit),yfinance",  # crypto→ccxt, stocks→yfinance
    ...
},
"ccxt_exchange": "binance",      # binance | bybit
"ccxt_market_type": "spot",      # spot | futures
```

### Vendor Chain Behavior
```bash
# Configured chain: ccxt(binance),ccxt(bybit),yfinance
# For BTC-USD:
#   1. Try ccxt(binance) → success → return data
#   2. On rate limit/error → try ccxt(bybit) → success → return data
#   3. On rate limit/error → try yfinance → fail (no crypto) → NoMarketDataError
```

### Symbol Mapping
| Pipeline Ticker | Exchange | Spot | Futures |
|-----------------|----------|------|---------|
| BTC-USD | Binance | BTC/USDT | BTC/USDT:USDT |
| ETH-USD | Bybit | ETH/USDT | ETH/USDT:USDT |
| SOL-USD | Binance | SOL/USDT | SOL/USDT:USDT |

### Caching Strategy
- Cache file: `{symbol}-{exchange}-{market_type}-OHLCV.csv`
- 2-year history downloaded on first request
- TTL: 15 minutes (900s) for same-day requests
- Daily refresh for historical dates

### Testing
```bash
$ .venv/bin/python -m pytest tests/test_vendor_routing.py -v
7 passed

$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped
```

### Files Created/Modified
| File | Purpose |
|------|---------|
| `tradingagents/dataflows/vendors/ccxt/ohlcv.py` | **New** — ccxt OHLCV vendor |
| `tradingagents/dataflows/vendors/ccxt/__init__.py` | **New** — ccxt vendor package |
| `tradingagents/dataflows/router.py` | Auto-route crypto → ccxt, vendor chain logic |
| `tradingagents/default_config.py` | New config keys: `ccxt_exchange`, `ccxt_market_type` |
| `tradingagents/dataflows/vendors/ccxt/ohlcv.py` | Point-in-time validation (dual stale check) |

### Verification
```bash
$ .venv/bin/python -c "
from tradingagents.dataflows.router import _is_crypto_symbol, route_to_vendor
from tradingagents.dataflows.config import set_config, get_config
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config['data_vendors']['core_stock_apis'] = 'ccxt(binance),ccxt(bybit),yfinance'
set_config(config)

print('BTC-USD:', _is_crypto_symbol('BTC-USD'))  # True
print('ETH-USD:', _is_crypto_symbol('ETH-USD'))  # True
print('AAPL:', _is_crypto_symbol('AAPL'))        # False
print('core_stock_apis:', get_config()['data_vendors']['core_stock_apis'])
# Output: ccxt(binance),ccxt(bybit),yfinance
"
```

### Verification
```bash
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped

$ .venv/bin/python -m ruff check .
All checks passed!
```