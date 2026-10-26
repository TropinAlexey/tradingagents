# SPEC: Point-in-Time Data Validation (Dual Stale Check)

## Summary
Implemented dual stale-data validation for OHLCV data: day-level check for backtest safety + minute-level check for live trading safety.

## Problem
Stale OHLCV data could feed wrong prices to agents:
- **Backtest**: yfinance occasionally returns year-old frames (#1021)
- **Live**: Cached data served during market hours with stale closes (partial candles)

## Solution
Dual stale-data validation in `tradingagents/dataflows/vendors/ccxt/ohlcv.py`.

### Dual Check Logic

```python
def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,      # 10 days
    max_stale_minutes: int = MAX_OHLCV_STALE_MINUTES, # 30 minutes
) -> None:
```

#### Check 1: Day-Level (Backtest Safety)
- Compares latest data row date vs `curr_date`
- Rejects if stale > 10 days
- Applies to ALL runs (backtest + live)

#### Check 2: Minute-Level (Live Safety)
- **Only triggers when `curr_date == today`** (live mode)
- Compares latest data timestamp vs `pd.Timestamp.now()`
- Rejects if stale > 30 minutes
- Prevents using partial intraday candles as final closes

### Constants
```python
MAX_OHLCV_STALE_DAYS = 10
MAX_OHLCV_STALE_MINUTES = 30  # Reject data older than 30 min for live runs
```

### Trigger Conditions

| Scenario | Check 1 (Days) | Check 2 (Minutes) | Result |
|----------|----------------|-------------------|--------|
| Backtest (2026-01-15) | ✅ Runs | ❌ Skipped (not today) | Day-level only |
| Live run (today) | ✅ Runs | ✅ Runs | Both checks |
| Cached data from yesterday | ✅ Runs | ❌ Skipped (not today) | Day-level only |
| Live run with 45-min old cache | ✅ Runs | ✅ Fails (>30 min) | Rejected |

### Error Messages
```python
# Day-level failure
"latest row is 2026-01-10, 15 days before requested 2026-01-25 (stale)"

# Minute-level failure (live only)
"latest row is 2026-10-26 14:15:00, 45.2 minutes old (max 30 min for live data)"
```

### Integration
Called at end of `load_ohlcv()` after all processing:
```python
def load_ohlcv(...) -> pd.DataFrame:
    ...
    _assert_ohlcv_not_stale(data, curr_date, symbol, ccxt_symbol)
    return data
```

### Why 30 Minutes?
- Market hours: 9:30-16:00 ET (6.5 hours)
- 30 min = ~7.7% of trading day
- Balances freshness vs. tolerance for brief API delays
- Configurable via `MAX_OHLCV_STALE_MINUTES`

### Files Modified
| File | Change |
|------|--------|
| `tradingagents/dataflows/vendors/ccxt/ohlcv.py` | Dual stale check, `MAX_OHLCV_STALE_MINUTES = 30` |

### Testing
```bash
# All tests pass
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped
```

### Configuration
```bash
# In .env or config
# Not directly configurable (constants in vendor)
# To adjust: modify MAX_OHLCV_STALE_MINUTES in ccxt/ohlcv.py
```

### Verification
```bash
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped

$ .venv/bin/python -m ruff check .
All checks passed!
```