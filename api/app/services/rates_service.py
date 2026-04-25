"""Interest rates and exchange rates data.

Real data sources:
  - FRED API: fredapi library (requires FRED_API_KEY env var)
    Series: DGS10 (US 10Y), FEDFUNDS, DEXJPUS (USD/JPY)
  - Yahoo Finance: yfinance library, ticker "JPY=X"
  - BOJ: https://www.stat-search.boj.or.jp/ (public CSV)

Each source falls back to mock data independently on failure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app.models.schemas import (
    BojRateDataPoint,
    ExchangeRateDataPoint,
    ExchangeRates,
    FredRateDataPoint,
    InterestRates,
    RatesResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_DATES = [
    (datetime(2024, 1, 1) + timedelta(days=30 * i)).strftime("%Y-%m-%d")
    for i in range(12)
]

_MOCK_FRED_RATES: list[dict] = [
    {"date": d, "us_10y_yield": round(4.2 + i * 0.05, 2), "fed_funds_rate": round(5.25 - i * 0.04, 2)}
    for i, d in enumerate(_DATES)
]

_MOCK_BOJ_RATES: list[dict] = [
    {"date": d, "policy_rate": round(-0.10 + i * 0.02, 2), "jgb_10y_yield": round(0.60 + i * 0.03, 2)}
    for i, d in enumerate(_DATES)
]

_MOCK_YAHOO_FX: list[dict] = [
    {"date": d, "usdjpy": round(148.0 + i * 0.5, 1)} for i, d in enumerate(_DATES)
]

_MOCK_FRED_FX: list[dict] = [
    {"date": d, "usdjpy": round(148.0 + i * 0.5, 1)} for i, d in enumerate(_DATES)
]


# ---------------------------------------------------------------------------
# Live data fetchers (each returns None on failure → triggers mock fallback)
# ---------------------------------------------------------------------------


def _fetch_fred_rates() -> list[FredRateDataPoint] | None:
    """Fetch US interest rates from FRED."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.info("FRED_API_KEY not set — using mock data")
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365)
        us10y = fred.get_series("DGS10", observation_start=start, observation_end=end)
        fedfunds = fred.get_series("FEDFUNDS", observation_start=start, observation_end=end)

        # Resample to monthly
        us10y_m = us10y.resample("MS").last().dropna()
        fedfunds_m = fedfunds.resample("MS").last().dropna()

        results: list[FredRateDataPoint] = []
        for dt in us10y_m.index:
            d_str = dt.strftime("%Y-%m-%d")
            ff = fedfunds_m.get(dt)
            results.append(
                FredRateDataPoint(
                    date=d_str,
                    us_10y_yield=round(float(us10y_m[dt]), 2),
                    fed_funds_rate=round(float(ff), 2) if ff is not None else None,
                )
            )
        return results if results else None
    except Exception:
        logger.exception("FRED rates fetch failed")
        return None


def _fetch_fred_fx() -> list[ExchangeRateDataPoint] | None:
    """Fetch USD/JPY from FRED."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365)
        fx = fred.get_series("DEXJPUS", observation_start=start, observation_end=end)
        fx_m = fx.resample("MS").last().dropna()
        return [
            ExchangeRateDataPoint(date=dt.strftime("%Y-%m-%d"), usdjpy=round(float(v), 1))
            for dt, v in fx_m.items()
        ] or None
    except Exception:
        logger.exception("FRED FX fetch failed")
        return None


def _fetch_yahoo_fx() -> list[ExchangeRateDataPoint] | None:
    """Fetch USD/JPY from Yahoo Finance."""
    try:
        import yfinance as yf

        ticker = yf.Ticker("JPY=X")
        hist = ticker.history(period="1y", interval="1mo")
        if hist.empty:
            return None
        results = [
            ExchangeRateDataPoint(
                date=dt.strftime("%Y-%m-%d"),
                usdjpy=round(float(row["Close"]), 1),
            )
            for dt, row in hist.iterrows()
        ]
        return results if results else None
    except Exception:
        logger.exception("Yahoo Finance FX fetch failed")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_rates() -> RatesResponse:
    """Return rates data with fallback to mock for each source."""

    # FRED interest rates
    fred_rates = _fetch_fred_rates()
    if fred_rates is None:
        fred_rates = [FredRateDataPoint(**d) for d in _MOCK_FRED_RATES]

    # BOJ rates — mock only for now
    boj_rates = [BojRateDataPoint(**d) for d in _MOCK_BOJ_RATES]

    # Yahoo Finance FX
    yahoo_fx = _fetch_yahoo_fx()
    if yahoo_fx is None:
        yahoo_fx = [ExchangeRateDataPoint(**d) for d in _MOCK_YAHOO_FX]

    # FRED FX
    fred_fx = _fetch_fred_fx()
    if fred_fx is None:
        fred_fx = [ExchangeRateDataPoint(**d) for d in _MOCK_FRED_FX]

    return RatesResponse(
        interest_rates=InterestRates(fred=fred_rates, boj=boj_rates),
        exchange_rates=ExchangeRates(yahoo_finance=yahoo_fx, fred=fred_fx),
    )
