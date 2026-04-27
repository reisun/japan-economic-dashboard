"""GDP Gap data: BOJ Output Gap Excel + FRED real GDP with HP-filter estimation.

Real data sources:
  - BOJ Output Gap: https://www.boj.or.jp/en/research/research_data/gap/gap.xlsx
    Sheet "data1", col A = quarter (e.g. "2024.1Q"), col B = output gap %.
  - FRED: series JPNRGDPEXP (Japan Real GDP, quarterly, seasonally adjusted).

Each source falls back to mock data independently on failure.
"""

from __future__ import annotations

import io
import logging
import os
import re
from datetime import date, datetime, timedelta

import numpy as np

from app.models.schemas import (
    CabinetOfficeGdpGap,
    EstimatedGdpGap,
    EstimatedGdpGapDataPoint,
    GdpGapDataPoint,
    GdpGapResponse,
)
from app.services.cache import cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_CABINET_DATA: list[dict] = [
    {"date": "2022-Q1", "gdp_gap_percent": -3.7},
    {"date": "2022-Q2", "gdp_gap_percent": -3.2},
    {"date": "2022-Q3", "gdp_gap_percent": -2.8},
    {"date": "2022-Q4", "gdp_gap_percent": -2.3},
    {"date": "2023-Q1", "gdp_gap_percent": -1.8},
    {"date": "2023-Q2", "gdp_gap_percent": -1.4},
    {"date": "2023-Q3", "gdp_gap_percent": -1.1},
    {"date": "2023-Q4", "gdp_gap_percent": -0.6},
    {"date": "2024-Q1", "gdp_gap_percent": -0.9},
    {"date": "2024-Q2", "gdp_gap_percent": -1.2},
    {"date": "2024-Q3", "gdp_gap_percent": -1.6},
    {"date": "2024-Q4", "gdp_gap_percent": -2.0},
]

# Simulated quarterly real GDP (in trillion yen, annualized)
_MOCK_REAL_GDP: list[float] = [
    535.0, 537.0, 539.5, 542.0,
    544.0, 546.0, 548.5, 551.0,
    549.0, 547.0, 545.0, 543.0,
]

_QUARTERS = [d["date"] for d in _MOCK_CABINET_DATA]


def _hp_filter(y: np.ndarray, lamb: float = 1600.0) -> np.ndarray:
    """Hodrick-Prescott filter: extract trend (potential GDP).

    Parameters
    ----------
    y : 1-D array of observations
    lamb : smoothing parameter (1600 for quarterly data)
    """
    n = len(y)
    if n < 4:
        return y.copy()

    # Build the penalty matrix (second-difference)
    diag = np.zeros(n)
    diag[0] = 1 + lamb
    diag[1] = 1 + 5 * lamb
    diag[2:-2] = 1 + 6 * lamb
    diag[-2] = 1 + 5 * lamb
    diag[-1] = 1 + lamb

    off1 = np.zeros(n - 1)
    off1[0] = -2 * lamb
    off1[1:-1] = -4 * lamb
    off1[-1] = -2 * lamb

    off2 = np.full(n - 2, lamb)

    from scipy.linalg import solve_banded

    ab = np.zeros((3, n))  # using tri-diagonal is not enough; use full band
    # Instead, construct sparse-like banded form via direct solve
    # For simplicity, use dense solve
    A = np.diag(diag) + np.diag(off1, 1) + np.diag(off1, -1) + np.diag(off2, 2) + np.diag(off2, -2)
    trend = np.linalg.solve(A, y)
    return trend


def _estimate_gdp_gap_average(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
    """平均概念のGDPギャップ。HPフィルターで潜在GDPを推計。"""
    y = np.array(real_gdp, dtype=float)
    potential = _hp_filter(y)
    results: list[EstimatedGdpGapDataPoint] = []
    for i, q in enumerate(quarters):
        gap_pct = round((y[i] - potential[i]) / potential[i] * 100, 2)
        results.append(
            EstimatedGdpGapDataPoint(
                date=q,
                real_gdp=round(float(y[i]), 1),
                potential_gdp=round(float(potential[i]), 1),
                gdp_gap_percent=gap_pct,
            )
        )
    return results


# 後方互換用エイリアス
_estimate_gdp_gap = _estimate_gdp_gap_average


# 最大概念のフォールバック・マークアップ（NOMINAL_GDP の 2%）
_MAXIMUM_NOMINAL_GDP = 560.0
_MAXIMUM_FALLBACK_RATIO = 0.02


def _estimate_gdp_gap_maximum(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
    """最大概念のGDPギャップ（MVP実装）。

    HPフィルター・トレンドに対して、正残差（実績 - トレンド）の75パーセンタイルを
    マークアップした水準を「最大概念の潜在GDP」として用いる。
    正残差が存在しない場合は NOMINAL_GDP * 0.02 をフォールバックで使う。

    NOTE: 本実装は MVP。本番運用では生産関数アプローチ
        （資本ストック・労働投入の最大稼働 → 潜在GDP）への
        差し替えポイント。具体的には _hp_filter / 75th-percentile マークアップを
        Cobb-Douglas + TFP トレンド + 完全雇用労働投入での再計算に置換する。
    """
    y = np.array(real_gdp, dtype=float)
    trend = _hp_filter(y)
    residuals = y - trend
    positive = residuals[residuals > 0]
    if positive.size > 0:
        markup = float(np.percentile(positive, 75))
    else:
        markup = _MAXIMUM_NOMINAL_GDP * _MAXIMUM_FALLBACK_RATIO
    potential_max = trend + markup

    results: list[EstimatedGdpGapDataPoint] = []
    for i, q in enumerate(quarters):
        gap_pct = round((y[i] - potential_max[i]) / potential_max[i] * 100, 2)
        results.append(
            EstimatedGdpGapDataPoint(
                date=q,
                real_gdp=round(float(y[i]), 1),
                potential_gdp=round(float(potential_max[i]), 1),
                gdp_gap_percent=gap_pct,
            )
        )
    return results


def _boj_quarter_to_label(raw: str) -> str | None:
    """Convert BOJ date format '2024.1Q' to 'YYYY-QN'."""
    m = re.match(r"(\d{4})\.(\d)Q", str(raw).strip())
    if m:
        return f"{m.group(1)}-Q{m.group(2)}"
    return None


def _pandas_quarter_to_label(ts) -> str:
    """Convert a pandas Timestamp (quarter-end) to 'YYYY-QN'."""
    return f"{ts.year}-Q{(ts.month - 1) // 3 + 1}"


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------


@cached("boj_gdp_gap")
def _fetch_boj_gdp_gap() -> list[GdpGapDataPoint] | None:
    """Fetch BOJ output gap data from their published Excel file."""
    try:
        import httpx
        import pandas as pd

        resp = httpx.get(
            "https://www.boj.or.jp/en/research/research_data/gap/gap.xlsx",
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()

        df = pd.read_excel(
            io.BytesIO(resp.content),
            sheet_name="data1",
            header=None,
            engine="openpyxl",
        )
        # Data rows start at index 5 (rows 0-4 are headers/units).
        # Col 0 = quarter label (e.g. "2024.1Q"), Col 1 = output gap %.
        data_df = df.iloc[5:].copy()
        data_df = data_df.dropna(subset=[0, 1])  # need both date and gap value

        results: list[GdpGapDataPoint] = []
        for _, row in data_df.iterrows():
            label = _boj_quarter_to_label(row[0])
            if label is None:
                continue
            results.append(
                GdpGapDataPoint(
                    date=label,
                    gdp_gap_percent=round(float(row[1]), 2),
                )
            )

        # Return last 20 quarters (~5 years)
        if results:
            return results[-20:]
        return None
    except Exception:
        logger.exception("BOJ GDP gap fetch failed")
        return None


@cached("fred_real_gdp")
def _fetch_real_gdp() -> tuple[list[float], list[str]] | None:
    """Fetch Japan real GDP quarterly data from FRED."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.info("FRED_API_KEY not set -- using mock real GDP")
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365 * 5)
        series = fred.get_series(
            "JPNRGDPEXP", observation_start=start, observation_end=end
        )
        series = series.dropna()
        if series.empty:
            return None

        gdp_values: list[float] = [round(float(v), 1) for v in series.values]
        quarter_labels: list[str] = [
            _pandas_quarter_to_label(ts) for ts in series.index
        ]
        return (gdp_values, quarter_labels) if gdp_values else None
    except Exception:
        logger.exception("FRED real GDP fetch failed")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_gdp_gap() -> GdpGapResponse:
    """Return GDP gap data. Falls back to mock on failure."""
    today = date.today().isoformat()

    # BOJ output gap data (replaces Cabinet Office mock)
    boj_data = _fetch_boj_gdp_gap()
    using_real_boj = boj_data is not None
    if boj_data is None:
        boj_data = [GdpGapDataPoint(**d) for d in _MOCK_CABINET_DATA]

    # Real GDP -> HP-filter estimation (平均概念) と 最大概念
    real_gdp_result = _fetch_real_gdp()
    try:
        if real_gdp_result is not None:
            gdp_values, quarters = real_gdp_result
        else:
            gdp_values, quarters = _MOCK_REAL_GDP, _QUARTERS
        average_data = _estimate_gdp_gap_average(gdp_values, quarters)
        maximum_data = _estimate_gdp_gap_maximum(gdp_values, quarters)
    except Exception:
        logger.exception("HP filter estimation failed, using raw mock")
        average_data = [
            EstimatedGdpGapDataPoint(
                date=q, real_gdp=g, potential_gdp=g, gdp_gap_percent=0.0
            )
            for q, g in zip(_QUARTERS, _MOCK_REAL_GDP)
        ]
        maximum_data = average_data

    average = EstimatedGdpGap(
        data=average_data, method="HP Filter (平均概念)", last_updated=today
    )
    maximum = EstimatedGdpGap(
        data=maximum_data,
        method="HP Filter + 75th-percentile markup (最大概念MVP)",
        last_updated=today,
    )

    return GdpGapResponse(
        cabinet_office=CabinetOfficeGdpGap(
            data=boj_data,
            source="日銀" if using_real_boj else "内閣府",
            last_updated=today,
        ),
        estimated_average=average,
        estimated_maximum=maximum,
        estimated=average,  # 後方互換エイリアス
    )
