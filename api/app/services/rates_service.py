"""Interest rates and exchange rates data.

Real data sources:
  - FRED API: fredapi library (requires FRED_API_KEY env var)
    Series: DGS10 (US 10Y), FEDFUNDS, DEXJPUS (USD/JPY)
    Series: IRSTCI01JPM156N (Japan call rate), IRLTLT01JPM156N (Japan 10Y JGB)
  - Yahoo Finance: yfinance library, ticker "JPY=X"

Each source falls back to mock data independently on failure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app.services.cache import cached
from app.services.common_range import filter_to_actual_range
from app.services.data_utils import (
    record_data_source_status,
    warn_fred_key_missing_once,
)

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


@cached("fred_rates")
def _fetch_fred_rates() -> list[FredRateDataPoint] | None:
    """Fetch US interest rates from FRED."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        warn_fred_key_missing_once()
        logger.debug("FRED_API_KEY not set — using mock for fred_rates")
        record_data_source_status("fred:rates", ok=False, detail="api_key_missing")
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
        if results:
            record_data_source_status(
                "fred:rates", ok=True, detail=f"points={len(results)}"
            )
            return results
        record_data_source_status("fred:rates", ok=False, detail="empty_series")
        return None
    except Exception as e:
        logger.exception("FRED rates fetch failed")
        record_data_source_status(
            "fred:rates", ok=False, detail=f"exception:{type(e).__name__}"
        )
        return None


@cached("fred_fx")
def _fetch_fred_fx() -> list[ExchangeRateDataPoint] | None:
    """Fetch USD/JPY from FRED."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        warn_fred_key_missing_once()
        record_data_source_status("fred:fx", ok=False, detail="api_key_missing")
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365)
        fx = fred.get_series("DEXJPUS", observation_start=start, observation_end=end)
        fx_m = fx.resample("MS").last().dropna()
        results = [
            ExchangeRateDataPoint(date=dt.strftime("%Y-%m-%d"), usdjpy=round(float(v), 1))
            for dt, v in fx_m.items()
        ]
        if results:
            record_data_source_status(
                "fred:fx", ok=True, detail=f"points={len(results)}"
            )
            return results
        record_data_source_status("fred:fx", ok=False, detail="empty_series")
        return None
    except Exception as e:
        logger.exception("FRED FX fetch failed")
        record_data_source_status(
            "fred:fx", ok=False, detail=f"exception:{type(e).__name__}"
        )
        return None


@cached("yahoo_fx")
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


@cached("boj_rates")
def _fetch_boj_rates() -> list[BojRateDataPoint] | None:
    """Fetch Japan interest rates from FRED (OECD via FRED).

    Series:
      IRSTCI01JPM156N  — Immediate Rates: Call Money/Interbank Rate (policy rate proxy)
      IRLTLT01JPM156N  — Long-Term Government Bond Yields: 10-Year (JGB 10Y)
    """
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        warn_fred_key_missing_once()
        logger.debug("FRED_API_KEY not set — using mock BOJ rates")
        record_data_source_status("fred:boj_rates", ok=False, detail="api_key_missing")
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365)
        call_rate = fred.get_series(
            "IRSTCI01JPM156N", observation_start=start, observation_end=end
        )
        jgb_10y = fred.get_series(
            "IRLTLT01JPM156N", observation_start=start, observation_end=end
        )

        # Resample to monthly
        call_m = call_rate.resample("MS").last().dropna()
        jgb_m = jgb_10y.resample("MS").last().dropna()

        results: list[BojRateDataPoint] = []
        # Use JGB index as primary (more likely to have data)
        for dt in jgb_m.index:
            d_str = dt.strftime("%Y-%m-%d")
            cr = call_m.get(dt)
            results.append(
                BojRateDataPoint(
                    date=d_str,
                    policy_rate=round(float(cr), 2) if cr is not None else None,
                    jgb_10y_yield=round(float(jgb_m[dt]), 2),
                )
            )
        if results:
            record_data_source_status(
                "fred:boj_rates", ok=True, detail=f"points={len(results)}"
            )
            return results
        record_data_source_status("fred:boj_rates", ok=False, detail="empty_series")
        return None
    except Exception as e:
        logger.exception("BOJ rates fetch failed (via FRED)")
        record_data_source_status(
            "fred:boj_rates", ok=False, detail=f"exception:{type(e).__name__}"
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_rates() -> RatesResponse:
    """Return rates data with fallback to mock for each source.

    各系列の取得成否（real / mock）はログに記録する。
    """

    status: dict[str, str] = {}

    # FRED interest rates
    fred_rates = _fetch_fred_rates()
    status["fred_rates"] = "real" if fred_rates else "mock"
    if fred_rates is None:
        fred_rates = [FredRateDataPoint(**d) for d in _MOCK_FRED_RATES]

    # BOJ rates (via FRED)
    boj_rates = _fetch_boj_rates()
    status["boj_rates"] = "real" if boj_rates else "mock"
    if boj_rates is None:
        boj_rates = [BojRateDataPoint(**d) for d in _MOCK_BOJ_RATES]

    # Yahoo Finance FX
    yahoo_fx = _fetch_yahoo_fx()
    status["yahoo_fx"] = "real" if yahoo_fx else "mock"
    if yahoo_fx is None:
        yahoo_fx = [ExchangeRateDataPoint(**d) for d in _MOCK_YAHOO_FX]

    # FRED FX
    fred_fx = _fetch_fred_fx()
    status["fred_fx"] = "real" if fred_fx else "mock"
    if fred_fx is None:
        fred_fx = [ExchangeRateDataPoint(**d) for d in _MOCK_FRED_FX]

    logger.info("rates data sources: %s", status)

    # 共通レンジ（GDPギャップ実績期間）に揃える
    fred_rates = filter_to_actual_range(fred_rates, label="fred_rates")
    boj_rates = filter_to_actual_range(boj_rates, label="boj_rates")
    yahoo_fx = filter_to_actual_range(yahoo_fx, label="yahoo_fx")
    fred_fx = filter_to_actual_range(fred_fx, label="fred_fx")

    return RatesResponse(
        interest_rates=InterestRates(fred=fred_rates, boj=boj_rates),
        exchange_rates=ExchangeRates(yahoo_finance=yahoo_fx, fred=fred_fx),
    )
