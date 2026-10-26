# SPEC: Multi-Venue Fallback (Bybit as Secondary Venue)

## Summary
Added Bybit as secondary ccxt venue for crypto OHLCV data, providing redundancy when Binance is rate-limited or unavailable.

## Problem
Single-venue dependency on Binance meant any rate limit, outage, or API change would cascade to yfinance (which doesn't support crypto), causing data failures.

## Solution
Added Bybit as second ccxt venue in the vendor chain with ordered fallback.

### Implementation

#### 1. Vendor Chain Configuration
```bash
# Default vendor chain in default_config.py
"core_stock_apis": "ccxt(binance),ccxt(bybit),yfinance"
```

#### 2. Router Fallback Logic
In `tradingagents/dataflows/router.py`:
```python
# For crypto symbols, ccxt vendors are prioritized
ccxt_vendors = [v for v in vendor_chain if v.startswith("ccxt(")]
other_vendors = [v for v in vendor_chain if not v.startswith("ccxt(")]
vendor_chain = ccxt_vendors + other_vendors
# Result: ["ccxt(binance)", "ccxt(bybit)", "yfinance"]
```

#### 3. Exchange-Specific Rate Limits
```python
SUPPORTED_EXCHANGES = {
    "binance": {
        "class": ccxt.binance,
        "rate_limit_ms": 1200,  # ~50 req/s
        "spot_suffix": "/USDT",
        "futures_suffix": "/USDT:USDT",
    },
    "bybit": {
        "class": ccxt.bybit,
        "rate_limit_ms": 100,   # 10 req/s (more aggressive)
        "spot_suffix": "/USDT",
        "futures_suffix": "/USDT:USDT",
    },
}
```

### Fallback Behavior
```python
# For BTC-USD:
# 1. Try ccxt(binance) → success → return data
# 2. On ccxt.RateLimitExceeded / NetworkError / ExchangeError:
#    → try ccxt(bybit) → success → return data
# 3. On ccxt.RateLimitExceeded / NetworkError / ExchangeError:
#    → try yfinance → fails (no crypto) → NoMarketDataError
```

### Exchange-Specific Details

| Feature | Binance | Bybit |
|---------|---------|-------|
| Rate limit | 1200ms (~50/s) | 100ms (~10/s) |
| Spot suffix | `/USDT` | `/USDT` |
| Futures suffix | `/USDT:USDT` | `/USDT:USDT` |
| Default market type | spot | spot |
| Authentication | Optional (higher limits) | Optional (higher limits) |

### Config Override
```bash
# Use Bybit as primary
TRADINGAGENTS_CCXT_EXCHANGE=bybit
TRADINGAGENTS_CCXT_MARKET_TYPE=spot

# Or futures
TRADINGAGENTS_CCXT_EXCHANGE=binance
TRADINGAGENTS_CCXT_MARKET_TYPE=futures
```

### Testing
```bash
$ .venv/bin/python -m pytest tests/test_vendor_routing.py -v
# Tests pass including multi-vendor fallback chain

$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped
```

### Files Modified
| File | Change |
|------|--------|
| `tradingagents/default_config.py` | Default vendor chain: `ccxt(binance),ccxt(bybit),yfinance` |
| `tradingagents/dataflows/router.py` | Auto-route crypto → ccxt vendors, ordered fallback |
| `tradingagents/dataflows/vendors/ccxt/ohlcv.py` | Bybit support in `SUPPORTED_EXCHANGES` |

### Verification
```bash
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped

$ .venv/bin/python -m ruff check .
All checks passed!
```