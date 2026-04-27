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


# ---------------------------------------------------------------------------
# e-Stat API helper
# ---------------------------------------------------------------------------


def estat_available() -> bool:
    """e-Stat API の appId が環境変数に設定されているかを返す。"""
    return bool(os.getenv("ESTAT_APP_ID"))


def fetch_estat_stats_data(
    stats_data_id: str,
    extra_params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict | None:
    """e-Stat API `getStatsData` を叩いて JSON を返す。

    Parameters
    ----------
    stats_data_id : 統計表ID（例 "0003427113"）
    extra_params : クラスフィルタ（cdCat01 等）など追加パラメータ
    """
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        logger.info("ESTAT_APP_ID not set -- skipping e-Stat fetch %s", stats_data_id)
        return None
    try:
        import httpx  # type: ignore

        url = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
        params: dict[str, Any] = {
            "appId": app_id,
            "statsDataId": stats_data_id,
            "metaGetFlg": "N",
            "cntGetFlg": "N",
            "lang": "J",
        }
        if extra_params:
            params.update(extra_params)
        resp = httpx.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # エラーチェック: GET_STATS_DATA.RESULT.STATUS が 0 以外はエラー
        result = data.get("GET_STATS_DATA", {}).get("RESULT", {})
        status = result.get("STATUS")
        if status not in (0, "0"):
            logger.warning(
                "e-Stat API returned non-zero status: %s, msg=%s",
                status,
                result.get("ERROR_MSG"),
            )
            return None
        logger.info("e-Stat %s fetched", stats_data_id)
        return data
    except Exception:
        logger.exception("e-Stat fetch failed for %s", stats_data_id)
        return None


def monthly_dict_to_quarterly_mean(monthly: dict[str, float]) -> dict[str, float]:
    """`{'YYYY-MM': value}` 形式の月次辞書 → `{'YYYY-Qn': mean}` 四半期辞書。

    四半期の各3ヶ月のうち、欠損があっても存在月の平均で算出する。
    完全に空の四半期は出力しない。
    """
    if not monthly:
        return {}
    bucket: dict[tuple[int, int], list[float]] = {}
    for ym, v in monthly.items():
        try:
            year_s, month_s = ym.split("-")
            year = int(year_s)
            month = int(month_s)
        except Exception:
            continue
        q = (month - 1) // 3 + 1
        bucket.setdefault((year, q), []).append(float(v))
    out: dict[str, float] = {}
    for (year, q), vals in bucket.items():
        if not vals:
            continue
        out[f"{year}-Q{q}"] = round(sum(vals) / len(vals), 2)
    return out
