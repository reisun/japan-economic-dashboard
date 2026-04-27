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
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-source status registry
#
# 各サービス（FRED / BOJ / e-Stat / その他）の最終取得結果を記録し、
# `/api/v1/health/data-sources` エンドポイントから参照できるようにする。
# secret は記録しない。値（ペイロード）も記録しない。
# ---------------------------------------------------------------------------


_status_lock = threading.Lock()
_data_source_status: dict[str, dict[str, Any]] = {}


def record_data_source_status(
    name: str,
    *,
    ok: bool,
    detail: str | None = None,
) -> None:
    """データソース取得の成否を登録する（最終時刻を上書き）。

    Parameters
    ----------
    name : データソース識別子（例 "fred:DGS10", "estat:cpi", "boj:fof"）
    ok : 取得成功なら True、失敗・未設定なら False
    detail : 任意の補足情報（失敗理由ラベル等）。secret は含めないこと。
    """
    with _status_lock:
        _data_source_status[name] = {
            "ok": bool(ok),
            "detail": detail,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }


def get_data_source_status() -> dict[str, dict[str, Any]]:
    """登録済みデータソース状態のスナップショットを返す。"""
    with _status_lock:
        return {k: dict(v) for k, v in _data_source_status.items()}


# ---------------------------------------------------------------------------
# FRED helpers
# ---------------------------------------------------------------------------


_fred_missing_warned = False


def fred_available() -> bool:
    """FRED API key が環境変数に設定されているかを返す。"""
    return bool(os.getenv("FRED_API_KEY"))


def warn_fred_key_missing_once() -> None:
    """FRED_API_KEY 未設定時、起動セッション中で最初の1回だけ警告ログを出す。"""
    global _fred_missing_warned
    if _fred_missing_warned:
        return
    _fred_missing_warned = True
    logger.warning(
        "FRED_API_KEY is not set; FRED-backed series will fall back to mock data. "
        "See README.md 'Setup' section for how to obtain and configure a key."
    )


def fetch_fred_series(series_id: str, years: int = 6) -> Any | None:
    """FRED から系列を pandas.Series として取得する。失敗・未設定時 None。

    Parameters
    ----------
    series_id : FRED 系列 ID
    years : 過去何年分を取得するか（YoY 計算に余裕を持たせるなら 6 推奨）

    取得成否は `record_data_source_status("fred:<series_id>", ...)` に記録する。
    """
    status_key = f"fred:{series_id}"
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        warn_fred_key_missing_once()
        logger.debug("FRED_API_KEY not set -- skipping %s", series_id)
        record_data_source_status(status_key, ok=False, detail="api_key_missing")
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
            record_data_source_status(status_key, ok=False, detail="empty_series")
            return None
        logger.info(
            "FRED %s fetched: %d points, %s..%s",
            series_id,
            len(series),
            series.index[0].date(),
            series.index[-1].date(),
        )
        record_data_source_status(
            status_key,
            ok=True,
            detail=f"points={len(series)}",
        )
        return series
    except Exception as e:
        logger.exception("FRED %s fetch failed", series_id)
        # 例外型のみ記録（メッセージにキー混入リスクを避ける）
        record_data_source_status(
            status_key, ok=False, detail=f"exception:{type(e).__name__}"
        )
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
    status_key = f"estat:{stats_data_id}"
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        logger.debug(
            "ESTAT_APP_ID not set -- skipping e-Stat fetch %s", stats_data_id
        )
        record_data_source_status(status_key, ok=False, detail="api_key_missing")
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
            record_data_source_status(
                status_key, ok=False, detail=f"api_status:{status}"
            )
            return None
        logger.info("e-Stat %s fetched", stats_data_id)
        record_data_source_status(status_key, ok=True, detail=None)
        return data
    except Exception as e:
        logger.exception("e-Stat fetch failed for %s", stats_data_id)
        record_data_source_status(
            status_key, ok=False, detail=f"exception:{type(e).__name__}"
        )
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
