"""ccxt-based OHLCV vendor for crypto (Binance, Bybit, etc.).

Uses ccxt to fetch OHLCV from crypto exchanges. Supports any exchange
that ccxt supports and provides USDT/USDC perpetual and spot markets.
"""

import logging
import os
import time
from datetime import timedelta

import ccxt
import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorRateLimitError
from tradingagents.dataflows.net import vendor_reachable
from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component

logger = logging.getLogger(__name__)

# Exchange-specific config
SUPPORTED_EXCHANGES = {
    "binance": {
        "class": ccxt.binance,
        "rate_limit_ms": 1200,  # 1200ms = ~50 req/s for public endpoints
        "spot_suffix": "/USDT",
        "futures_suffix": "/USDT:USDT",
    },
    "bybit": {
        "class": ccxt.bybit,
        "rate_limit_ms": 100,  # 100ms = 10 req/s
        "spot_suffix": "/USDT",
        "futures_suffix": "/USDT:USDT",
    },
}

MAX_OHLCV_STALE_DAYS = 10
MAX_OHLCV_STALE_MINUTES = 30  # reject data older than 30 minutes for point-in-time safety
OHLCV_CACHE_TTL_SECONDS = 900
CCXT_HOST = "https://api.binance.com"  # for reachability check


def _ccxt_exchange(exchange_id: str) -> ccxt.Exchange:
    """Create a ccxt exchange instance with rate limiting."""
    exchange_id = exchange_id.lower()
    if exchange_id not in SUPPORTED_EXCHANGES:
        raise ValueError(f"Unsupported exchange: {exchange_id}. Supported: {list(SUPPORTED_EXCHANGES.keys())}")

    cfg = SUPPORTED_EXCHANGES[exchange_id]
    exchange_class = cfg["class"]

    # Create instance with rate limiting enabled
    exchange = exchange_class({
        "enableRateLimit": True,
        "rateLimit": cfg["rate_limit_ms"],
        "timeout": 30000,  # 30s
        "options": {
            "defaultType": "spot",  # default to spot
        },
    })

    # Set API keys if available (for higher rate limits)
    api_key = os.environ.get(f"{exchange_id.upper()}_API_KEY")
    secret = os.environ.get(f"{exchange_id.upper()}_SECRET")
    if api_key and secret:
        exchange.apiKey = api_key
        exchange.secret = secret

    return exchange


def _pipeline_ticker_to_ccxt(ticker: str, market_type: str = "spot", exchange_id: str = "binance") -> str:
    """Convert pipeline ticker (BTC-USD) to ccxt symbol (BTC/USDT or BTC/USDT:USDT)."""
    base = ticker.split("-")[0].upper()
    exchange_id = exchange_id.lower()
    cfg = SUPPORTED_EXCHANGES[exchange_id]

    if market_type == "futures":
        return f"{base}{cfg['futures_suffix']}"
    return f"{base}{cfg['spot_suffix']}"


def _raise_for_empty(ticker: str, ccxt_symbol: str, what: str) -> None:
    """Report empty ccxt result as NoMarketDataError."""
    if not vendor_reachable(CCXT_HOST):
        raise VendorRateLimitError(f"Exchange {CCXT_HOST} unreachable; no {what}")
    raise NoMarketDataError(ticker, ccxt_symbol, f"no {what}")


def _ccxt_retry(func, max_retries: int = 3, base_delay: float = 2.0):
    """Execute ccxt call with exponential backoff on rate limits."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except ccxt.RateLimitExceeded as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"ccxt rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise VendorRateLimitError(f"ccxt rate limit exceeded: {e}") from e
        except ccxt.NetworkError as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"ccxt network error, retrying in {delay:.0f}s: {e}")
                time.sleep(delay)
            else:
                raise VendorRateLimitError(f"ccxt network error: {e}") from e
        except ccxt.ExchangeError as e:
            # Exchange-specific errors (symbol not found, etc.)
            raise NoMarketDataError("", "", f"exchange error: {e}") from e


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Ensure the DataFrame has a 'Date' column."""
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date", "timestamp"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize OHLCV DataFrame."""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], utc=True).dt.tz_localize(None)

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    return data.dropna(subset=["Date"]).copy()


def _fill_price_gaps(data: pd.DataFrame) -> pd.DataFrame:
    """Forward/back-fill price gaps."""
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data = data.dropna(subset=["Close"]).copy()
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
    max_stale_minutes: int = MAX_OHLCV_STALE_MINUTES,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date or current time.

    Two checks:
    1. Day-level: latest row not older than max_stale_days vs curr_date (backtest safety)
    2. Minute-level: latest row not older than max_stale_minutes vs now (point-in-time safety)
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = pd.to_datetime(data["Date"], errors="coerce").dropna()
    if dates.empty:
        return
    latest = dates.max()

    # Day-level check (backtest safety)
    latest_day = latest.normalize()
    stale_days = (requested - latest_day).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest_day.date()}, {stale_days} days before "
            f"requested {requested.date()} (stale)",
        )

    # Minute-level check (point-in-time safety for live runs)
    # Only apply when curr_date is today (live mode)
    now = pd.Timestamp.today().normalize()
    if requested == now:
        stale_minutes = (pd.Timestamp.now() - latest).total_seconds() / 60
        if stale_minutes > max_stale_minutes:
            raise NoMarketDataError(
                symbol,
                canonical,
                f"latest row is {latest}, {stale_minutes:.0f} minutes old "
                f"(max {max_stale_minutes} min for live data)",
            )


def load_ohlcv(
    symbol: str,
    curr_date: str,
    fill_gaps: bool = True,
    exchange_id: str | None = None,
    market_type: str | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV from ccxt exchange with caching.

    Args:
        symbol: Pipeline ticker (e.g., "BTC-USD")
        curr_date: Cutoff date in YYYY-MM-DD (no look-ahead)
        fill_gaps: Forward-fill price gaps for indicators
        exchange_id: "binance" or "bybit" (reads from config if None)
        market_type: "spot" or "futures" (reads from config if None)

    Returns:
        DataFrame with columns: Date, Open, High, Low, Close, Volume
        Filtered to curr_date (no look-ahead bias).
    """
    # Read exchange/market_type from config if not provided
    if exchange_id is None or market_type is None:
        config = get_config()
        if exchange_id is None:
            exchange_id = config.get("ccxt_exchange", "binance")
        if market_type is None:
            market_type = config.get("ccxt_market_type", "spot")
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date).normalize()

    # Cache file per symbol + exchange + market type
    now = pd.Timestamp.today()
    start_date = now - timedelta(days=365 * 2)  # 2 years
    start_str = start_date.strftime("%Y-%m-%d")
    (now + timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-{exchange_id}-{market_type}-OHLCV.csv",
    )

    # Check cache
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            written = pd.Timestamp.fromtimestamp(os.path.getmtime(data_file))
            if written.date() == now.date() or curr_date_dt.date() < now.date():
                data = cached

    ccxt_symbol = _pipeline_ticker_to_ccxt(symbol, market_type, exchange_id)

    if data is None:
        exchange = _ccxt_exchange(exchange_id)

        # Switch market type for futures
        if market_type == "futures":
            exchange.options["defaultType"] = "swap"
        else:
            exchange.options["defaultType"] = "spot"

        try:
            ohlcv = _ccxt_retry(lambda: exchange.fetch_ohlcv(
                ccxt_symbol,
                timeframe="1d",
                since=exchange.parse8601(start_str + " 00:00:00"),
                limit=1000,
            ))
        except Exception as e:
            raise NoMarketDataError(symbol, ccxt_symbol, f"fetch failed: {e}") from e

        if not ohlcv:
            _raise_for_empty(symbol, ccxt_symbol, "price rows")

        # Convert to DataFrame
        df = pd.DataFrame(ohlcv, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["Date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]

        # Cache
        df.to_csv(data_file, index=False, encoding="utf-8")
        data = df

    data = _clean_dataframe(data)

    # Filter to curr_date (no look-ahead)
    data = data[data["Date"] <= curr_date_dt]

    # Drop unsettled bar (NaN close at the end)
    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        settled = data["Close"].notna().to_numpy().nonzero()[0]
        if settled.size == 0:
            raise NoMarketDataError(symbol, ccxt_symbol, "no bar has closing price")
        data = data.iloc[:settled[-1] + 1]

    data = _fill_price_gaps(data) if fill_gaps else data.dropna(subset=["Close"]).copy()

    _assert_ohlcv_not_stale(data, curr_date, symbol, ccxt_symbol)

    return data
