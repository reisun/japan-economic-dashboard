"""Inflation indicators: CPIコアコア、GDPデフレータ、賃金上昇率（前年同期比%）。

思想:
  ギャップ単独ではなく「ギャップ × インフレ率」のマトリクスで政策判断する。
  インフレ率を制約条件、ギャップを目的関数として運用する。

CPI 指標選定について:
  日本の「コア（生鮮食品除く総合）」はエネルギー価格急変動の影響を強く受け、
  基調インフレ指標としては不適切。世界標準（FRB, ECB等）の "core CPI" は
  食料・エネルギーを除いた基調指標で、これは日本の「コアコア（生鮮食品及び
  エネルギー除く総合）」に対応する。日銀も近年はコアコアを基調判断で重視している。
  本ダッシュボードでは世界標準に揃え、コアコアを採用する。

データソース（実データ取得）:
  - GDPデフレータ: FRED `NGDPDSAIXJPQ` (Gross Domestic Product Deflator for
      Japan, Quarterly) → 前年同期比%。OECD経由で内閣府SNAデータが反映される。
  - 名目賃金: FRED `LCEAMN01JPM659S` (Labor Compensation: Earnings:
      Manufacturing: Hourly for Japan, Monthly, Growth rate same period
      previous year) → 月次 YoY を四半期平均化。
      製造業ベースだが、毎月勤労統計の現金給与総額YoYと近似的に連動。
  - CPI コアコア（生鮮食品及びエネルギー除く総合・前年同月比%）:
      FRED の Japan core CPI (CPGRLE01JPM659N 等) は 2021年6月で discontinued。
      A) e-Stat API（要 ESTAT_APP_ID）→ B) 総務省統計局CSV直接取得 の順で試行し、
      いずれも失敗時はモック値にフォールバック。月次取得後、四半期平均で集計する。
      e-Stat 取得手順: https://www.e-stat.go.jp/api/api-info/api-guide
      参考: https://www.stat.go.jp/data/cpi/

実データ取得失敗時は警告ログ → モック値にフォールバック（破壊しない）。
"""

from __future__ import annotations

import logging
import re
from datetime import date

from app.models.schemas import InflationDataPoint, InflationResponse
from app.services.cache import cached
from app.services.common_range import filter_to_actual_range
from app.services.data_utils import (
    fetch_estat_stats_data,
    fetch_fred_series,
    monthly_dict_to_quarterly_mean,
    quarterize_monthly,
    to_quarter_labelled,
    yoy_pct_quarterly,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock data: 12四半期分（GDPギャップと同じ系列）
# ---------------------------------------------------------------------------

_MOCK_INFLATION: list[dict] = [
    {"date": "2022-Q1", "cpi_core_core": 0.6, "gdp_deflator": 0.4, "wage_growth": 0.6},
    {"date": "2022-Q2", "cpi_core_core": 1.6, "gdp_deflator": 0.5, "wage_growth": 1.3},
    {"date": "2022-Q3", "cpi_core_core": 2.0, "gdp_deflator": 0.6, "wage_growth": 1.6},
    {"date": "2022-Q4", "cpi_core_core": 2.4, "gdp_deflator": 1.2, "wage_growth": 1.9},
    {"date": "2023-Q1", "cpi_core_core": 2.6, "gdp_deflator": 2.0, "wage_growth": 1.4},
    {"date": "2023-Q2", "cpi_core_core": 2.5, "gdp_deflator": 3.6, "wage_growth": 1.4},
    {"date": "2023-Q3", "cpi_core_core": 2.4, "gdp_deflator": 5.1, "wage_growth": 1.0},
    {"date": "2023-Q4", "cpi_core_core": 2.3, "gdp_deflator": 3.9, "wage_growth": 1.2},
    {"date": "2024-Q1", "cpi_core_core": 2.4, "gdp_deflator": 3.4, "wage_growth": 2.0},
    {"date": "2024-Q2", "cpi_core_core": 2.4, "gdp_deflator": 3.2, "wage_growth": 4.5},
    {"date": "2024-Q3", "cpi_core_core": 2.3, "gdp_deflator": 2.4, "wage_growth": 2.8},
    {"date": "2024-Q4", "cpi_core_core": 2.2, "gdp_deflator": 2.0, "wage_growth": 3.1},
]
_MOCK_BY_DATE = {d["date"]: d for d in _MOCK_INFLATION}


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------


@cached("fred_gdp_deflator_yoy")
def _fetch_gdp_deflator_yoy() -> dict[str, float] | None:
    """GDPデフレータ前年同期比%を FRED から取得。"""
    series = fetch_fred_series("NGDPDSAIXJPQ", years=6)
    if series is None:
        return None
    return yoy_pct_quarterly(series)


@cached("fred_wage_growth_yoy")
def _fetch_wage_growth_yoy() -> dict[str, float] | None:
    """名目賃金前年同期比%を FRED から取得（製造業時給 YoY を四半期平均化）。"""
    series = fetch_fred_series("LCEAMN01JPM659S", years=6)
    if series is None:
        return None
    quarterly = quarterize_monthly(series, how="mean")
    return to_quarter_labelled(quarterly)


# ---------------------------------------------------------------------------
# CPI コアコア（生鮮食品及びエネルギーを除く総合）前年同月比%
#   FRED が 2021/6 で discontinued のため、独自取得経路を実装する。
#
#   優先順位:
#     A. e-Stat API (要 ESTAT_APP_ID 環境変数)
#        統計表ID: 0003427113 (消費者物価指数 月次 全国 2020年基準)
#        対象系列: 「生鮮食品及びエネルギーを除く総合」前年同月比
#     B. 総務省統計局 CSV 直接取得（zsi2020s.html の "前年同月比" CSV）
#        URL: https://www.stat.go.jp/data/cpi/historic.html
#     C. どちらも失敗 → None（呼び出し側でモックフォールバック）
# ---------------------------------------------------------------------------

# e-Stat 統計表ID（CPI 全国 月次 2020年基準）。環境変数で上書き可。
_ESTAT_CPI_STATS_DATA_ID_DEFAULT = "0003427113"

# 「生鮮食品及びエネルギーを除く総合」を識別する候補文字列
_CORE_CORE_NAME_HINTS = (
    "生鮮食品及びエネルギーを除く総合",
    "生鮮食品及びエネルギ-を除く総合",
    "生鮮食品及びエネルギーを除く",
)
# 前年同月比を識別する候補文字列
_YOY_NAME_HINTS = (
    "前年同月比",
    "対前年同月比",
)


def _estat_extract_cpi_core_core_yoy(payload: dict) -> dict[str, float]:
    """e-Stat getStatsData レスポンスから CPI コアコア前年同月比%の月次辞書を抽出。

    e-Stat の構造:
      GET_STATS_DATA.STATISTICAL_DATA.CLASS_INF.CLASS_OBJ[]: 各分類軸の定義
      GET_STATS_DATA.STATISTICAL_DATA.DATA_INF.VALUE[]: データセル
        各 VALUE は @cat01, @cat02, @time, @unit, $: 値
    """
    try:
        sd = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]
        class_inf = sd.get("CLASS_INF", {}).get("CLASS_OBJ", [])
        values = sd.get("DATA_INF", {}).get("VALUE", [])
        if isinstance(values, dict):
            values = [values]
        if not values:
            return {}

        # CLASS_OBJ から「指数の種類（前年同月比）」「品目（生鮮食品及びエネルギーを除く総合）」
        # に対応するコードを決定する。CLASS_OBJ は配列のことも単一dictのこともある。
        if isinstance(class_inf, dict):
            class_inf = [class_inf]

        # 軸ID(@id) → {コード: 名前}
        axis_codes: dict[str, dict[str, str]] = {}
        for axis in class_inf:
            axis_id = axis.get("@id")
            classes = axis.get("CLASS", [])
            if isinstance(classes, dict):
                classes = [classes]
            axis_codes[axis_id] = {c.get("@code"): c.get("@name", "") for c in classes}

        # 「前年同月比」「コアコア」のコードを探す
        target_yoy_codes: set[tuple[str, str]] = set()  # (axis_id, code)
        target_item_codes: set[tuple[str, str]] = set()
        for axis_id, codes in axis_codes.items():
            for code, name in codes.items():
                if any(h in name for h in _YOY_NAME_HINTS):
                    target_yoy_codes.add((axis_id, code))
                if any(h in name for h in _CORE_CORE_NAME_HINTS):
                    target_item_codes.add((axis_id, code))

        if not target_yoy_codes:
            logger.warning("e-Stat CPI: 前年同月比 のコードが見つからない")
            return {}
        if not target_item_codes:
            logger.warning("e-Stat CPI: 生鮮食品及びエネルギーを除く総合 のコードが見つからない")
            return {}

        # @ プレフィクス付きの軸キーに変換
        def axis_key(axis_id: str) -> str:
            return f"@{axis_id}"

        out: dict[str, float] = {}
        for v in values:
            # YoY 軸チェック
            yoy_match = any(v.get(axis_key(aid)) == code for aid, code in target_yoy_codes)
            item_match = any(v.get(axis_key(aid)) == code for aid, code in target_item_codes)
            if not (yoy_match and item_match):
                continue
            time_code = v.get("@time", "")  # 例: "2024000101" or "2024010000"
            # e-Stat の time コードは "YYYYMM00" 形式（月次）
            m = re.match(r"^(\d{4})(\d{2})", str(time_code))
            if not m:
                continue
            year = int(m.group(1))
            month = int(m.group(2))
            if not (1 <= month <= 12):
                continue
            try:
                val = float(v.get("$"))
            except (TypeError, ValueError):
                continue
            out[f"{year:04d}-{month:02d}"] = val
        return out
    except Exception:
        logger.exception("e-Stat CPI レスポンスのパースに失敗")
        return {}


def _fetch_cpi_core_core_via_estat() -> dict[str, float] | None:
    """e-Stat API 経由で CPI コアコア前年同月比% (月次) を取得。"""
    import os as _os

    stats_data_id = _os.getenv("ESTAT_CPI_STATS_DATA_ID", _ESTAT_CPI_STATS_DATA_ID_DEFAULT)
    payload = fetch_estat_stats_data(stats_data_id)
    if payload is None:
        return None
    monthly = _estat_extract_cpi_core_core_yoy(payload)
    if not monthly:
        logger.warning("e-Stat: CPI コアコア前年同月比の抽出に失敗")
        return None
    logger.info("e-Stat CPI core-core YoY: %d months fetched", len(monthly))
    return monthly


def _fetch_cpi_core_core_via_stat_csv() -> dict[str, float] | None:
    """総務省統計局の公開CSV/Excelから CPI コアコア前年同月比% (月次) を取得（フォールバックB）。

    総務省統計局は CPI 時系列を複数の Excel/CSV で配布している。
    安定して機械可読なエンドポイント（CSV）として、以下を試行する。

      https://www.stat.go.jp/data/cpi/2020/index.html 配下の zenkoku_zen.csv
      （全国 月次 全分類; 2020年基準）

    URL は変動する可能性があるため、複数候補を順に試す。
    """
    import io

    try:
        import httpx  # type: ignore
        import pandas as pd  # type: ignore
    except Exception:
        logger.exception("CSV フォールバックの依存ライブラリが不足")
        return None

    candidates = [
        # 2020年基準 全国 月次 CSV（総務省統計局）
        "https://www.stat.go.jp/data/cpi/2020/zsi/csv/zsi2020m.csv",
        "https://www.stat.go.jp/data/cpi/2020/zsi/csv/zsi2020s.csv",
    ]

    for url in candidates:
        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            if resp.status_code != 200:
                logger.info("CPI CSV %s -> HTTP %s", url, resp.status_code)
                continue
            content = resp.content
            # 文字コード自動判定（CP932 / UTF-8 双方を試行）
            df = None
            for enc in ("cp932", "utf-8-sig", "utf-8"):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, header=None, dtype=str)
                    break
                except Exception:
                    continue
            if df is None:
                logger.info("CPI CSV %s: pandas read_csv 失敗", url)
                continue

            # df の構造を簡単にスキャン:
            #   - 「生鮮食品及びエネルギーを除く総合」を含む行を探す
            #   - 「前年同月比」を含む列セットを特定する
            # 構造が想定と違えば次候補へ。
            text = df.fillna("").astype(str)

            # 「前年同月比」を含む行/列をフラグ
            yoy_row = None
            for i in range(min(len(text), 10)):
                row = " ".join(text.iloc[i].tolist())
                if any(h in row for h in _YOY_NAME_HINTS):
                    yoy_row = i
                    break

            target_row = None
            for i in range(len(text)):
                row = " ".join(text.iloc[i].tolist())
                if any(h in row for h in _CORE_CORE_NAME_HINTS):
                    if any(h in row for h in _YOY_NAME_HINTS):
                        target_row = i
                        break

            if target_row is None:
                logger.info("CPI CSV %s: 対象行が見つからない", url)
                continue

            # 月次の値を抽出: 年月ヘッダ列（例 "2024年1月" / "2024/1" など）と値の対応を探す
            # 簡略化: target_row の右側を横方向に、ヘッダ行（最初の数行のいずれか）と突合
            monthly: dict[str, float] = {}
            row_vals = text.iloc[target_row].tolist()
            # ヘッダ候補行: 0..min(5, target_row-1)
            header_candidates = [text.iloc[i].tolist() for i in range(min(target_row, 6))]
            for col_idx in range(len(row_vals)):
                cell = row_vals[col_idx].strip()
                if not cell or cell in ("-", "*"):
                    continue
                try:
                    val = float(cell.replace(",", ""))
                except ValueError:
                    continue
                # ヘッダから年月を推定
                ym = None
                for hdr in header_candidates:
                    if col_idx >= len(hdr):
                        continue
                    h = hdr[col_idx].strip()
                    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月", h)
                    if m:
                        ym = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
                        break
                    m = re.match(r"^(\d{4})[/-](\d{1,2})", h)
                    if m:
                        ym = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
                        break
                if ym:
                    monthly[ym] = val

            if monthly:
                logger.info("CPI CSV %s: %d months parsed", url, len(monthly))
                return monthly
            logger.info("CPI CSV %s: 月次値の抽出に失敗", url)
        except Exception:
            logger.exception("CPI CSV %s の取得・パース失敗", url)
            continue

    return None


@cached("cpi_core_core_yoy")
def _fetch_cpi_core_core_yoy() -> dict[str, float] | None:
    """CPIコアコア前年同月比%を取得し四半期平均で返す。

    A: e-Stat API → B: 総務省統計局 CSV → 失敗時 None。
    """
    monthly = _fetch_cpi_core_core_via_estat()
    source = "estat"
    if monthly is None:
        monthly = _fetch_cpi_core_core_via_stat_csv()
        source = "stat_csv"
    if monthly is None:
        logger.info("CPI core-core: real fetch failed (e-Stat & CSV) -- will fall back to mock")
        return None

    quarterly = monthly_dict_to_quarterly_mean(monthly)
    if not quarterly:
        logger.warning("CPI core-core: 月次→四半期集計に失敗（source=%s）", source)
        return None
    logger.info(
        "CPI core-core YoY fetched via %s: %d months -> %d quarters",
        source,
        len(monthly),
        len(quarterly),
    )
    return quarterly


def _build_real_inflation() -> tuple[list[dict] | None, dict[str, str]]:
    """実データ取得を試み、四半期ごとに 3 系列をマージした list[dict] を返す。

    取得失敗系列はモック値にフォールバック。
    Returns: (data, source_status_per_series)
    """
    deflator = _fetch_gdp_deflator_yoy() or {}
    wage = _fetch_wage_growth_yoy() or {}
    cpi = _fetch_cpi_core_core_yoy() or {}

    status = {
        "gdp_deflator": "real" if deflator else "mock",
        "wage_growth": "real" if wage else "mock",
        "cpi_core_core": "real" if cpi else "mock",
    }
    logger.info("inflation data sources: %s", status)

    # 取得できた四半期 + モックの四半期を統合
    all_quarters = sorted(set(deflator) | set(wage) | set(cpi) | set(_MOCK_BY_DATE))
    if not all_quarters:
        return None, status

    out: list[dict] = []
    for q in all_quarters:
        mock = _MOCK_BY_DATE.get(q, {})
        out.append({
            "date": q,
            "cpi_core_core": cpi.get(q, mock.get("cpi_core_core")),
            "gdp_deflator": deflator.get(q, mock.get("gdp_deflator")),
            "wage_growth": wage.get(q, mock.get("wage_growth")),
        })
    return out, status


async def get_inflation() -> InflationResponse:
    """インフレ率3系列を返す。実データ取得失敗系列はモックにフォールバック。"""
    today = date.today().isoformat()
    raw, status = _build_real_inflation()
    if raw is None:
        raw = _MOCK_INFLATION
        status = {"cpi_core_core": "mock", "gdp_deflator": "mock", "wage_growth": "mock"}

    has_real = any(v == "real" for v in status.values())
    suffix = "" if has_real else "（モック）"
    source = (
        f"総務省CPI（コアコア）[{status['cpi_core_core']}] / "
        f"内閣府GDPデフレータ via FRED [{status['gdp_deflator']}] / "
        f"厚労省毎月勤労統計 via FRED [{status['wage_growth']}]{suffix}"
    )

    points = [InflationDataPoint(**d) for d in raw]
    points = filter_to_actual_range(points, label="inflation")
    return InflationResponse(
        data=points,
        source=source,
        boj_target=2.0,
        last_updated=today,
    )
