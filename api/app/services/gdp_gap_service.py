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


# ---------------------------------------------------------------------------
# 最大概念潜在GDP: Cobb-Douglas 生産関数アプローチ
# ---------------------------------------------------------------------------
#
# 思想:
#   「潜在」は本来「持てる力の最大値」。ギャップは構造的に ≤ 0 で運用すべき
#   （0% を上回るのは概念の混乱）。投資が進めば潜在GDPも増える、という
#   ストック・労働投入の能力ベースで推計する。
#
# モデル:
#   Y_potential_t = A_trend_t * (L_full_t)^(1-α) * (K_t)^α
#   - α: 資本分配率（日本は 0.33 が定型値）
#   - A_t: TFP（全要素生産性）。実績Yから A_t = Y_t / (L_t^(1-α) * K_t^α)
#         で逆算し、HPフィルター（λ=1600）でトレンド抽出 → A_trend_t
#   - L_full_t: 完全雇用労働投入
#         = 労働力人口_t × 平均労働時間_t × (1 - NAIRU)
#     NAIRU は日本基準で 2.5% 固定（構造的失業率）
#   - K_t: 民間資本ストック（実績）。投資フローの累積で増えていく
#
# 実データ差し替え点（TODO）:
#   - 労働力人口・就業者数: 総務省統計局「労働力調査」
#   - 平均労働時間: 厚労省「毎月勤労統計」
#   - 失業率実績: 同 労働力調査
#   - 民間資本ストック: 内閣府「民間企業資本ストック」(SNA系列)
#   現状はモック定数。実データ取得時は _MOCK_LABOR_FORCE / _MOCK_HOURS /
#   _MOCK_UNEMPLOYMENT / _MOCK_CAPITAL_STOCK を差し替え、_fetch_macro_inputs()
#   フックで上書きすれば本実装はそのまま使える設計。
# ---------------------------------------------------------------------------

# 構造パラメータ
_CD_ALPHA = 0.33  # 資本分配率（日本標準）
_NAIRU = 0.025  # 構造的失業率 2.5%

# モック投入要素（_QUARTERS と同じ12四半期; 単位は名目スケール）
# 労働力人口（百万人）— 緩やかな減少トレンド
_MOCK_LABOR_FORCE: list[float] = [
    69.0, 69.0, 68.9, 68.8,
    68.8, 68.7, 68.6, 68.5,
    68.5, 68.4, 68.3, 68.2,
]
# 平均労働時間（時間/月）
_MOCK_HOURS: list[float] = [
    138.0, 138.5, 138.8, 139.0,
    139.2, 139.5, 139.8, 140.0,
    139.8, 139.5, 139.2, 139.0,
]
# 実績失業率（%）— 観測値。完全雇用なら NAIRU=2.5%
_MOCK_UNEMPLOYMENT: list[float] = [
    2.7, 2.6, 2.6, 2.5,
    2.6, 2.6, 2.5, 2.5,
    2.6, 2.7, 2.7, 2.8,
]
# 民間資本ストック（兆円, 実質）— 緩やかに増加
_MOCK_CAPITAL_STOCK: list[float] = [
    1860.0, 1865.0, 1870.0, 1876.0,
    1882.0, 1888.0, 1895.0, 1902.0,
    1908.0, 1914.0, 1920.0, 1926.0,
]


def _estimate_gdp_gap_maximum(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
    """最大概念のGDPギャップ（Cobb-Douglas 生産関数アプローチ）。

    Y_potential = A_trend * L_full^(1-α) * K^α
    で完全雇用ベースの潜在GDPを推計する。実績Yから TFP を逆算 → HP平滑化で
    トレンド抽出 → 完全雇用労働投入と実績資本ストックを掛け合わせる。

    実績失業率 ≥ NAIRU である限り L_full ≥ L_実績 となるため、構造上
    Y_potential ≥ Y_実績、つまりギャップは ≤ 0 に収まりやすい設計。

    NOTE: 現状はモックパラメータ（_MOCK_LABOR_FORCE 等）。
          実データ差し替えは _fetch_macro_inputs() を実装する（上のドキュメント参照）。
    """
    n = len(real_gdp)
    y = np.array(real_gdp, dtype=float)

    # データ長を実績GDPに合わせて補正（FRED 実データ時の長さ違いに耐える）
    def _resize(seq: list[float]) -> np.ndarray:
        if len(seq) == n:
            return np.array(seq, dtype=float)
        if len(seq) > n:
            return np.array(seq[-n:], dtype=float)
        # 末尾値で前方延長
        pad = [seq[0]] * (n - len(seq))
        return np.array(pad + seq, dtype=float)

    labor_force = _resize(_MOCK_LABOR_FORCE)
    hours = _resize(_MOCK_HOURS)
    unemployment = _resize(_MOCK_UNEMPLOYMENT) / 100.0  # % → 比率
    capital = _resize(_MOCK_CAPITAL_STOCK)

    # 実績労働投入 L_t = 労働力人口 × 労働時間 × (1 - 実績失業率)
    L_actual = labor_force * hours * (1.0 - unemployment)
    # 完全雇用労働投入 L_full = 労働力人口 × 労働時間 × (1 - NAIRU)
    L_full = labor_force * hours * (1.0 - _NAIRU)

    # 実績Yから TFP 逆算（A_t = Y_t / (L_t^(1-α) * K_t^α)）
    denom_actual = (L_actual ** (1.0 - _CD_ALPHA)) * (capital ** _CD_ALPHA)
    A_implied = y / denom_actual
    # TFPトレンド: HPフィルター後、これまで観測した最大値で「フロンティア」を取る。
    # 「潜在 = 持てる力の最大値」の思想に合わせ、実績TFPがトレンドを上回った
    # 期は当該水準を以後の潜在生産性として保持する（hysteresis 風の上方シフト）。
    A_smoothed = _hp_filter(A_implied)
    A_frontier = np.maximum(A_smoothed, A_implied)
    A_max = np.maximum.accumulate(A_frontier)

    # 完全雇用ベースの潜在GDP
    potential_max = A_max * (L_full ** (1.0 - _CD_ALPHA)) * (capital ** _CD_ALPHA)

    # 数値スケールが実績Yと整合するよう、必要に応じて単位整合をかけている
    # （A_implied 自体に Y のスケール情報が乗るので、追加スケールは不要）

    results: list[EstimatedGdpGapDataPoint] = []
    for i, q in enumerate(quarters):
        pot = float(potential_max[i])
        # ガード: 何らかの数値異常で潜在 ≤ 0 になった場合は実績で代替
        if not np.isfinite(pot) or pot <= 0:
            pot = float(y[i])
        gap_pct = round((float(y[i]) - pot) / pot * 100, 2)
        results.append(
            EstimatedGdpGapDataPoint(
                date=q,
                real_gdp=round(float(y[i]), 1),
                potential_gdp=round(pot, 1),
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
        method="Cobb-Douglas 生産関数 (TFPトレンド × 完全雇用労働投入 × 資本ストック, α=0.33, NAIRU=2.5%)",
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
