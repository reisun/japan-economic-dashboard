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
  - CPI コアコア: TODO (URL検証要)
      FRED の Japan core CPI (CPGRLE01JPM659N 等) は 2021年6月で discontinued。
      e-Stat API（要 appId）か総務省統計局 CSV 直接取得が必要。
      現時点ではモック値にフォールバック。
      参考: https://www.stat.go.jp/data/cpi/

実データ取得失敗時は警告ログ → モック値にフォールバック（破壊しない）。
"""

from __future__ import annotations

import logging
from datetime import date

from app.models.schemas import InflationDataPoint, InflationResponse
from app.services.cache import cached
from app.services.common_range import filter_to_actual_range
from app.services.data_utils import (
    fetch_fred_series,
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


@cached("cpi_core_core_yoy")
def _fetch_cpi_core_core_yoy() -> dict[str, float] | None:
    """CPIコアコア前年同月比%を取得。

    TODO (URL検証要):
      FRED の Japan core CPI は 2021年6月で discontinued。
      e-Stat API（appId 必要）または総務省統計局CSVから取得する必要がある。
      現状は実装せず None を返してモックフォールバック。
    """
    logger.info("CPI core-core: real fetch not implemented (FRED discontinued, e-Stat needs appId) -- using mock")
    return None


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
