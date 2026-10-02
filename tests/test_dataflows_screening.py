"""Tests for the auto-scan screening module (tradingagents/dataflows/screening.py).

Unit-scoped: no network, no ccxt, no yfinance — the universe builders are
faked at the module seam and the screen runs on synthetic OHLCV frames. The
metrics contract is asserted exactly (momentum/trend/volume math) because the
score gates which instruments earn an LLM pipeline run.
"""

import pandas as pd
import pytest

from tradingagents.dataflows import screening
from tradingagents.dataflows.errors import NoMarketDataError, VendorError

pytestmark = pytest.mark.unit


def _ohlcv_frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2026-09-01", periods=len(closes), freq="D")
    data = {"Date": dates, "Close": closes}
    if volumes is None:
        volumes = [1000.0] * len(closes)
    data["Volume"] = volumes
    return pd.DataFrame(data)


def test_screen_one_scores_strong_uptrend_with_volume(monkeypatch):
    """20 rising closes ending high on a volume spike cross all three gates."""
    closes = [100.0 + i for i in range(20)] + [135.0]  # momentum 35%, above SMA20
    volumes = [1000.0] * 20 + [2500.0]
    monkeypatch.setattr(
        screening, "load_ohlcv", lambda ticker, date, fill_gaps: _ohlcv_frame(closes, volumes)
    )
    candidate = screening.screen_one("BTC-USD", "2026-10-01")
    assert candidate is not None
    assert candidate.asset_type == "crypto"
    assert candidate.score == pytest.approx(4.0)  # 2 (capped) + 1 trend + 1 volume
    assert candidate.momentum_pct == pytest.approx(35.0)
    assert candidate.trend_pct > 2
    # the window includes the spike itself: mean = (19*1000 + 2500)/20 = 1075
    assert candidate.volume_ratio == pytest.approx(2500 / 1075, rel=1e-3)
    assert any("SMA20" in reason for reason in candidate.reasons)


def test_screen_one_flat_series_scores_zero_and_no_reasons(monkeypatch):
    closes = [100.0] * 25
    monkeypatch.setattr(
        screening, "load_ohlcv", lambda ticker, date, fill_gaps: _ohlcv_frame(closes)
    )
    candidate = screening.screen_one("NVDA", "2026-10-01")
    assert candidate is not None
    assert candidate.score == 0.0
    assert candidate.reasons == []
    assert candidate.asset_type == "stock"


def test_screen_one_known_crypto_base_gets_crypto_type(monkeypatch):
    closes = [100.0] * 25
    monkeypatch.setattr(
        screening, "load_ohlcv", lambda ticker, date, fill_gaps: _ohlcv_frame(closes)
    )
    candidate = screening.screen_one("ETH-USD", "2026-10-01")
    assert candidate is not None
    assert candidate.asset_type == "crypto"  # ETH is in the pipeline's closed set


def test_screen_one_thin_data_returns_none(monkeypatch):
    monkeypatch.setattr(
        screening, "load_ohlcv", lambda ticker, date, fill_gaps: _ohlcv_frame([100.0, 101.0])
    )
    assert screening.screen_one("NVDA", "2026-10-01") is None


def test_screen_one_vendor_error_returns_none_not_raised(monkeypatch):
    def boom(ticker, date, fill_gaps):
        raise NoMarketDataError(ticker, ticker, "no rows")

    monkeypatch.setattr(screening, "load_ohlcv", boom)
    assert screening.screen_one("AAPL", "2026-10-01") is None


def test_screen_universe_ranks_and_truncates(monkeypatch):
    def fake_load(ticker, date, fill_gaps):
        if ticker == "HI":
            return _ohlcv_frame([100.0 + i * 2 for i in range(21)])
        if ticker == "MID":
            return _ohlcv_frame([100.0 + i * 0.5 for i in range(21)])
        return _ohlcv_frame([100.0] * 21)  # LO flat → score 0, still a candidate

    monkeypatch.setattr(screening, "load_ohlcv", fake_load)
    ranked = screening.screen_universe(["LO", "HI"], ["MID"], "2026-10-01", top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["ticker"] == "HI"
    assert ranked[1]["ticker"] == "MID"


def test_screen_universe_keeps_universe_asset_type_for_off_set_crypto(monkeypatch):
    """Liquid crypto outside the closed executable set (QNT-USD) must keep the
    crypto type from its universe, not fall back to closed-set inference."""
    closes = [100.0 + i * 2 for i in range(21)]
    monkeypatch.setattr(
        screening, "load_ohlcv", lambda ticker, date, fill_gaps: _ohlcv_frame(closes)
    )
    ranked = screening.screen_universe(["QNT-USD"], [], "2026-10-01", top_n=5)
    (candidate,) = ranked
    assert candidate["ticker"] == "QNT-USD"
    assert candidate["asset_type"] == "crypto"


def test_crypto_universe_via_module_seam(monkeypatch):
    """The ccxt client is resolved through getattr(ccxt, exchange_id); the fake
    stands in at that exact seam."""
    import sys
    import types

    class FakeExchange:
        symbols = ["BTC/USDT", "USDC/USDT", "DOGE/USDT", "ZEC/USDT", "ETH/BTC"]

        def __init__(self, config):
            pass

        def market(self, symbol):
            return {"base": symbol.split("/", 1)[0]}

        def fetch_tickers(self):
            return {
                "BTC/USDT": {"quoteVolume": 1_000_000_000},
                "USDC/USDT": {"quoteVolume": 3_000_000_000},
                "DOGE/USDT": {"quoteVolume": 82_000_000},
                "ZEC/USDT": {"quoteVolume": 4_000_000},
                "ETH/BTC": {"quoteVolume": 9_000_000_000},
            }

    fake_ccxt = types.SimpleNamespace(binance=FakeExchange)
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)

    universe = screening.crypto_universe({"exec_exchange_id": "binance"}, top_n=5)
    assert universe == ["BTC-USD", "DOGE-USD"]  # stablecoin dropped, thin dropped, non-USDT dropped


def test_crypto_universe_failure_raises_vendor_error(monkeypatch):
    import sys
    import types

    class Broken:
        def __init__(self, config):
            pass

        def fetch_tickers(self):
            raise OSError("connection refused")

    fake_ccxt = types.SimpleNamespace(binance=Broken)
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)
    with pytest.raises(VendorError):
        screening.crypto_universe({"exec_exchange_id": "binance"}, top_n=5)


def test_stock_universe_falls_back_when_screener_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("screener down")

    # The function imports yfinance inside its body, so patch the source module.
    import yfinance

    monkeypatch.setattr(yfinance, "EquityQuery", boom, raising=False)
    monkeypatch.setattr(yfinance, "screen", boom, raising=False)
    universe = screening.stock_universe({}, top_n=5)
    assert universe == list(screening._STOCK_UNIVERSE_FALLBACK[:5])
