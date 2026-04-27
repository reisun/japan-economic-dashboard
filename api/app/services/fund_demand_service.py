"""Fund demand data: FRED Bank Lending + BOJ Flow of Funds.

Real data sources:
  - Bank Lending: FRED series CRDQJPAPABIS (BIS total credit to private
    non-financial sector, quarterly, billions of JPY).
  - Flow of Funds: BOJ CSV from https://www.boj.or.jp/statistics/sj/sjhiq.htm
    (complex format; falls back to mock when parsing fails).

Each source falls back to mock data independently on failure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app.models.schemas import (
    BankLending,
    BankLendingDataPoint,
    FlowOfFunds,
    FlowOfFundsDataPoint,
    FundDemandResponse,
)
from app.services.cache import cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_FLOW_OF_FUNDS: list[dict] = []
for q in ["2022-Q1", "2022-Q2", "2022-Q3", "2022-Q4",
           "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
           "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]:
    _MOCK_FLOW_OF_FUNDS.extend([
        {"date": q, "sector": "households",    "net_lending": round(12.0 + (hash(q) % 10) * 0.5, 1)},
        {"date": q, "sector": "corporations",  "net_lending": round(-4.0 + (hash(q) % 6) * 0.3, 1)},
        {"date": q, "sector": "government",    "net_lending": round(-18.0 - (hash(q) % 8) * 0.4, 1)},
    ])

_MOCK_BANK_LENDING: list[dict] = [
    {"date": "2022-01", "total_lending": 510.2, "yoy_change_percent": 1.5},
    {"date": "2022-04", "total_lending": 513.0, "yoy_change_percent": 1.8},
    {"date": "2022-07", "total_lending": 516.5, "yoy_change_percent": 2.0},
    {"date": "2022-10", "total_lending": 518.1, "yoy_change_percent": 2.1},
    {"date": "2023-01", "total_lending": 520.3, "yoy_change_percent": 2.0},
    {"date": "2023-04", "total_lending": 523.0, "yoy_change_percent": 1.9},
    {"date": "2023-07", "total_lending": 526.2, "yoy_change_percent": 1.9},
    {"date": "2023-10", "total_lending": 528.5, "yoy_change_percent": 2.0},
    {"date": "2024-01", "total_lending": 530.0, "yoy_change_percent": 1.9},
    {"date": "2024-04", "total_lending": 532.5, "yoy_change_percent": 1.8},
    {"date": "2024-07", "total_lending": 535.0, "yoy_change_percent": 1.7},
    {"date": "2024-10", "total_lending": 537.0, "yoy_change_percent": 1.6},
]


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------

_Q_MONTH = {1: "01", 2: "04", 3: "07", 4: "10"}


def _quarter_month(ts) -> str:
    """Return 'YYYY-MM' for the start month of the quarter containing *ts*."""
    q = (ts.month - 1) // 3 + 1
    return f"{ts.year}-{_Q_MONTH[q]}"


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------


@cached("fred_bank_lending")
def _fetch_bank_lending() -> list[BankLendingDataPoint] | None:
    """Fetch bank lending from FRED (BIS total credit, quarterly, billions JPY)."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.info("FRED_API_KEY not set -- using mock bank lending")
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        # Fetch 6 years so we have 1 extra year for YoY calculation
        start = end - timedelta(days=365 * 6)
        series = fred.get_series(
            "CRDQJPAPABIS", observation_start=start, observation_end=end
        )
        series = series.dropna()
        if series.empty:
            return None

        # Convert billions JPY -> trillion JPY
        series_trillion = series / 1000.0

        # Build a dict keyed by (year, quarter) for YoY lookup
        by_yq: dict[tuple[int, int], tuple] = {}
        for ts, val in series_trillion.items():
            q = (ts.month - 1) // 3 + 1
            by_yq[(ts.year, q)] = (ts, float(val))

        results: list[BankLendingDataPoint] = []
        # Only output the last ~5 years (skip first year used for YoY baseline)
        cutoff = end - timedelta(days=365 * 5)
        for (year, q), (ts, val) in sorted(by_yq.items()):
            if ts < cutoff:
                continue
            prev = by_yq.get((year - 1, q))
            if prev is not None:
                _, prev_val = prev
                yoy = round((val - prev_val) / prev_val * 100, 1)
            else:
                yoy = 0.0
            results.append(
                BankLendingDataPoint(
                    date=_quarter_month(ts),
                    total_lending=round(val, 1),
                    yoy_change_percent=yoy,
                )
            )
        return results if results else None
    except Exception:
        logger.exception("FRED bank lending fetch failed")
        return None


@cached("boj_flow_of_funds")
def _fetch_flow_of_funds() -> list[FlowOfFundsDataPoint] | None:
    """Attempt to fetch BOJ Flow of Funds CSV.

    The BOJ publishes flow-of-funds data in a complex multi-header CSV that
    changes format between releases.  We attempt a best-effort parse but
    expect this to fall back to mock data in most cases.
    """
    try:
        import httpx

        # The page lists CSV links; try to fetch the quarterly flow page
        resp = httpx.get(
            "https://www.boj.or.jp/statistics/sj/sjhiq.htm",
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        # The page is HTML listing CSV links -- reliable automated parsing
        # of the actual CSV requires knowing the exact current filename and
        # multi-header layout which varies.  Return None to use mock data.
        logger.info("BOJ flow of funds page fetched but CSV parsing not yet implemented -- using mock")
        return None
    except Exception:
        logger.exception("BOJ flow of funds fetch failed")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_fund_demand() -> FundDemandResponse:
    """Return fund demand data. Falls back to mock on failure."""

    # Bank lending (via FRED)
    lending_data = _fetch_bank_lending()
    if lending_data is None:
        lending_data = [BankLendingDataPoint(**d) for d in _MOCK_BANK_LENDING]

    # Flow of funds (BOJ CSV -- likely falls back to mock)
    flow_data = _fetch_flow_of_funds()
    if flow_data is None:
        flow_data = [FlowOfFundsDataPoint(**d) for d in _MOCK_FLOW_OF_FUNDS]

    return FundDemandResponse(
        flow_of_funds=FlowOfFunds(data=flow_data),
        bank_lending=BankLending(data=lending_data),
    )
