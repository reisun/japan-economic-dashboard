"""共通データ取得・整形ユーティリティ。

各サービスから呼ばれる共通ヘルパを集約する。
- FRED 系列の取得（API キー無し時は None）
- 月次 → 四半期集計
- 前年同期比（YoY）計算
- 四半期ラベル変換 ("YYYY-Qn")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FRED helpers
# ---------------------------------------------------------------------------


def fred_available() -> bool:
    """FRED API key が環境変数に設定されているかを返す。"""
    return bool(os.getenv("FRED_API_KEY"))


def fetch_fred_series(series_id: str, years: int = 6) -> Any | None:
    """FRED から系列を pandas.Series として取得する。失敗・未設定時 None。

    Parameters
    ----------
    series_id : FRED 系列 ID
    years : 過去何年分を取得するか（YoY 計算に余裕を持たせるなら 6 推奨）
    """
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.info("FRED_API_KEY not set -- skipping %s", series_id)
        return None
    try:
        from fredapi import Fred  # type: ignore

        fred = Fred(api_key=api_key)
        end = datetime.now()
        start = end - timedelta(days=365 * years)
        series = fred.get_series(
            series_id, observation_start=start, observation_end=end
        )
        series = series.dropna()
        if series.empty:
            logger.warning("FRED %s returned empty series", series_id)
            return None
        logger.info(
            "FRED %s fetched: %d points, %s..%s",
            series_id,
            len(series),
            series.index[0].date(),
            series.index[-1].date(),
        )
        return series
    except Exception:
        logger.exception("FRED %s fetch failed", series_id)
        return None


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------


def quarter_label(ts) -> str:
    """pandas.Timestamp / datetime → 'YYYY-Qn'."""
    q = (ts.month - 1) // 3 + 1
    return f"{ts.year}-Q{q}"


def month_to_quarter_label(year: int, month: int) -> str:
    q = (month - 1) // 3 + 1
    return f"{year}-Q{q}"


def quarterize_monthly(series, how: str = "mean"):
    """月次 pandas.Series → 四半期 pandas.Series。

    how : "mean" | "last" | "sum"
    """
    if series is None:
        return None
    rule = "QS"  # quarter start
    if how == "mean":
        return series.resample(rule).mean().dropna()
    if how == "last":
        return series.resample(rule).last().dropna()
    if how == "sum":
        return series.resample(rule).sum().dropna()
    raise ValueError(f"unknown how={how!r}")


# ---------------------------------------------------------------------------
# YoY calculation
# ---------------------------------------------------------------------------


def yoy_pct_quarterly(series) -> dict[str, float]:
    """四半期 pandas.Series から `{'YYYY-Qn': yoy_pct}` の辞書を返す。

    前年同四半期と比較。前年データが無い四半期は省略。
    """
    if series is None or len(series) == 0:
        return {}
    by_yq: dict[tuple[int, int], float] = {}
    for ts, v in series.items():
        q = (ts.month - 1) // 3 + 1
        by_yq[(ts.year, q)] = float(v)

    out: dict[str, float] = {}
    for (year, q), v in by_yq.items():
        prev = by_yq.get((year - 1, q))
        if prev is None or prev == 0:
            continue
        out[f"{year}-Q{q}"] = round((v - prev) / prev * 100, 2)
    return out


def to_quarter_labelled(series) -> dict[str, float]:
    """四半期 pandas.Series → `{'YYYY-Qn': value}` 辞書。"""
    if series is None:
        return {}
    return {quarter_label(ts): round(float(v), 2) for ts, v in series.items()}
