"""Market screening for the auto-scan: build a tradeable universe and rank it.

One job: given nothing but the current date, decide *which* instruments are
worth the expensive per-ticker LLM pipeline. Two sources, both already in the
dependency tree:

* crypto — ccxt public market data (no credentials needed for tickers) on the
  configured ``exec_exchange_id``; ranked by 24h quote volume, mapped to the
  pipeline's Yahoo form (``BTC-USD``). Stablecoins and pairs with no Yahoo
  quote are dropped.
* stocks — Yahoo's equity screener (``yfinance.screen``): US equities above a
  market-cap floor, largest first. The screener is a live surface, so every
  failure degrades to the static large-cap fallback list rather than raising.

The screen itself is deliberately LLM-free and cheap: momentum, trend and
volume-pressure metrics from the cached OHLCV series each candidate maps to,
scored into a bounded number with a human-readable ``reason``. Point-in-time
integrity holds because ``load_ohlcv`` already filters to ``curr_date``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tradingagents.dataflows.errors import VendorError
from tradingagents.dataflows.symbols import crypto_base
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

logger = logging.getLogger(__name__)

# Stablecoins carry no trade thesis and skew volume rankings; exclude by base.
_STABLECOIN_BASES = frozenset(
    {"USDC", "USD1", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "AEUR"}
)

# A base must have this much 24h quote volume to be worth a pipeline run.
MIN_QUOTE_VOLUME_USD = 5_000_000

# Screener floor: US equities below this market cap are illiquid for the plan path.
_MIN_STOCK_MARKET_CAP = 10_000_000_000

# Static fallback for the Yahoo screener: liquid US large caps. Kept in engine
# code (not server state) so every consumer sees the same universe.
_STOCK_UNIVERSE_FALLBACK: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "BRK-B", "AVGO", "JPM", "LLY", "V", "XOM", "UNH", "MA", "COST", "HD",
    "PG", "JNJ", "NFLX", "WMT", "ORCL", "MRK", "AMD", "CRM", "BAC", "KO",
    "PEP", "ABBV", "TMO", "CVX", "ADBE", "DIS", "WFC", "CSCO", "ACN", "MCD",
)


@dataclass
class Candidate:
    """One screened instrument with its metrics, ranked by score."""

    ticker: str
    asset_type: str
    score: float
    last_close: float
    momentum_pct: float
    trend_pct: float
    volume_ratio: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "score": round(self.score, 4),
            "last_close": self.last_close,
            "momentum_pct": round(self.momentum_pct, 2),
            "trend_pct": round(self.trend_pct, 2),
            "volume_ratio": round(self.volume_ratio, 3),
            "reasons": list(self.reasons),
        }


def crypto_universe(config: dict, top_n: int) -> list[str]:
    """Top ``top_n`` liquid crypto as pipeline tickers (``BTC-USD`` form).

    Public exchange data only — no credentials are read or sent. Bases the
    pipeline's closed crypto set does not know are kept: the OHLCV vendor
    resolves any Yahoo-listed ``BASE-USD`` and the bridge plans through
    ``exec_symbol_overrides`` if one of them ever earns a plan.
    """
    exchange_id = str(config.get("exec_exchange_id") or "binance")
    import ccxt  # lazy like bridge.py: importing dataflows stays cheap

    try:
        exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        tickers = exchange.fetch_tickers()
    except Exception as exc:  # noqa: BLE001 — any ccxt/network failure degrades
        raise VendorError(f"crypto universe unavailable via {exchange_id}: {exc}") from exc

    ranked: list[tuple[str, float]] = []
    for symbol, ticker in tickers.items():
        if not isinstance(symbol, str) or not symbol.endswith("/USDT"):
            continue
        market = exchange.market(symbol) if exchange_id else None
        try:
            base = str(market.get("base", "")) if market else symbol.split("/", 1)[0]
            quote_volume = float(ticker.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            continue
        if base in _STABLECOIN_BASES or quote_volume < MIN_QUOTE_VOLUME_USD:
            continue
        ranked.append((f"{base}-USD", quote_volume))

    ranked.sort(key=lambda entry: -entry[1])
    seen: set[str] = set()
    out: list[str] = []
    for ticker, _volume in ranked:
        if ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
        if len(out) >= top_n:
            break
    return out


def stock_universe(config: dict, top_n: int) -> list[str]:
    """Top ``top_n`` US equities by market cap as pipeline tickers.

    Yahoo's screener is the source; its failures degrade to the static
    large-cap fallback so an outage never blocks an auto-scan entirely.
    """
    try:
        from yfinance import EquityQuery, screen

        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", ["region", "us"]),
                EquityQuery("gt", ["intradaymarketcap", _MIN_STOCK_MARKET_CAP]),
            ],
        )
        response = screen(query, size=top_n, sortField="intradaymarketcap", sortAsc=False)
        rows = response.get("quotes", []) if isinstance(response, dict) else []
        symbols = [str(row.get("symbol", "")).strip() for row in rows]
        out = [symbol for symbol in symbols if symbol]
    except Exception as exc:  # noqa: BLE001 — screener is best-effort
        logger.warning("stock screener failed (%s: %s); using static universe", type(exc).__name__, exc)
        out = []
    if not out:
        out = list(_STOCK_UNIVERSE_FALLBACK)
    return out[:top_n]


def _metrics(data, lookback: int) -> tuple[float, float, float, float] | None:
    """(last_close, momentum_pct, trend_pct, volume_ratio) or None for thin data."""
    close = data["Close"].dropna()
    volume = data["Volume"].dropna() if "Volume" in data else None
    if len(close) < lookback + 1:
        return None
    last = float(close.iloc[-1])
    momentum = (last / float(close.iloc[-lookback - 1]) - 1.0) * 100.0
    window = close.iloc[-lookback:]
    avg = float(window.mean())
    trend = (last / avg - 1.0) * 100.0
    if volume is not None and len(volume) >= lookback:
        ratio = float(volume.iloc[-1]) / max(float(volume.iloc[-lookback:].mean()), 1e-12)
    else:
        ratio = 1.0
    return last, momentum, trend, ratio


def screen_one(
    ticker: str,
    curr_date: str,
    lookback: int = 20,
    asset_type: str | None = None,
) -> Candidate | None:
    """Score one ticker on its OHLCV series; None when data is unavailable.

    ``asset_type`` comes from the universe that produced the ticker — the
    universe builders know the truth, and guessing here mislabels liquid
    crypto outside the closed executable set (QNT-USD, WLD-USD) as stocks.
    Only an unscreened ticker (direct call) falls back to the closed-set
    inference.
    """
    if asset_type is None:
        asset_type = "crypto" if crypto_base(ticker) else "stock"
    try:
        data = load_ohlcv(ticker, curr_date, fill_gaps=True)
        metrics = _metrics(data, lookback)
    except VendorError as exc:
        logger.info("screening %s skipped: %s", ticker, exc)
        return None
    except (OSError, ValueError, KeyError) as exc:
        logger.info("screening %s skipped: %s: %s", ticker, type(exc).__name__, exc)
        return None
    if metrics is None:
        return None
    last, momentum, trend, ratio = metrics

    score = 0.0
    reasons: list[str] = []
    if momentum >= 5.0:
        score += min(abs(momentum) / 10.0, 2.0)
        reasons.append(f"+{momentum:.1f}% trong {lookback} phiên")
    elif momentum <= -5.0:
        score += min(abs(momentum) / 15.0, 1.5)
        reasons.append(f"{momentum:.1f}% trong {lookback} phiên (quá bán tiềm năng)")
    if trend >= 2.0:
        score += 1.0
        reasons.append("giá trên SMA20 (xu hướng tăng)")
    elif trend <= -2.0:
        score += 0.5
        reasons.append("giá dưới SMA20 (xu hướng giảm)")
    if ratio >= 1.5:
        score += min((ratio - 1.0), 1.0)
        reasons.append(f"khối lượng phiên cuối x{ratio:.1f} so với trung bình")

    return Candidate(
        ticker=ticker,
        asset_type=asset_type,
        score=score,
        last_close=last,
        momentum_pct=momentum,
        trend_pct=trend,
        volume_ratio=ratio,
        reasons=reasons,
    )


def screen_universe(
    crypto: list[str],
    stocks: list[str],
    curr_date: str,
    top_n: int,
    lookback: int = 20,
) -> list[dict]:
    """Rank both universes by screen score; return the top ``top_n`` as dicts.

    Tickers keep the asset type of the universe they came from — that type
    decides the LLM analysts and the advisory/plan path downstream.
    """
    candidates: list[Candidate] = []
    for ticker in crypto:
        candidate = screen_one(ticker, curr_date, lookback, asset_type="crypto")
        if candidate is not None:
            candidates.append(candidate)
    for ticker in stocks:
        candidate = screen_one(ticker, curr_date, lookback, asset_type="stock")
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda c: (-c.score, c.ticker))
    return [candidate.as_dict() for candidate in candidates[:top_n]]
