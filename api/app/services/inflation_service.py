"""Inflation indicators: CPI コア、GDPデフレータ、賃金上昇率（前年同期比%）。

思想:
  ギャップ単独ではなく「ギャップ × インフレ率」のマトリクスで政策判断する。
  インフレ率を制約条件、ギャップを目的関数として運用する。

データソース（実データ差し替え点）:
  - CPI コア: 総務省統計局「消費者物価指数」生鮮食品を除く総合（前年同月比%）
      https://www.stat.go.jp/data/cpi/
  - GDPデフレータ: 内閣府「四半期別GDP速報」総合デフレータ（前年同期比%）
      https://www.esri.cao.go.jp/jp/sna/menu.html
  - 名目賃金: 厚労省「毎月勤労統計調査」現金給与総額（前年同月比%）
      https://www.mhlw.go.jp/toukei/list/30-1a.html

現状はモック値（月次相当の四半期スナップショット）。実装は将来差し替え可能なよう、
get_inflation() が _fetch_real_inflation() フックを呼んでから _MOCK_INFLATION
にフォールバックする構造にしてある。
"""

from __future__ import annotations

import logging
from datetime import date

from app.models.schemas import InflationDataPoint, InflationResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock data: 12四半期分（GDPギャップと同じ系列）
# 直近の実勢を意識した値（CPIコアは2022年後半から上振れ、賃金は遅れて反応）
# ---------------------------------------------------------------------------

_MOCK_INFLATION: list[dict] = [
    {"date": "2022-Q1", "cpi_core": 0.6, "gdp_deflator": 0.4, "wage_growth": 0.6},
    {"date": "2022-Q2", "cpi_core": 1.6, "gdp_deflator": 0.5, "wage_growth": 1.3},
    {"date": "2022-Q3", "cpi_core": 2.5, "gdp_deflator": 0.6, "wage_growth": 1.6},
    {"date": "2022-Q4", "cpi_core": 3.7, "gdp_deflator": 1.2, "wage_growth": 1.9},
    {"date": "2023-Q1", "cpi_core": 3.5, "gdp_deflator": 2.0, "wage_growth": 1.4},
    {"date": "2023-Q2", "cpi_core": 3.3, "gdp_deflator": 3.6, "wage_growth": 1.4},
    {"date": "2023-Q3", "cpi_core": 2.9, "gdp_deflator": 5.1, "wage_growth": 1.0},
    {"date": "2023-Q4", "cpi_core": 2.5, "gdp_deflator": 3.9, "wage_growth": 1.2},
    {"date": "2024-Q1", "cpi_core": 2.6, "gdp_deflator": 3.4, "wage_growth": 2.0},
    {"date": "2024-Q2", "cpi_core": 2.6, "gdp_deflator": 3.2, "wage_growth": 4.5},
    {"date": "2024-Q3", "cpi_core": 2.4, "gdp_deflator": 2.4, "wage_growth": 2.8},
    {"date": "2024-Q4", "cpi_core": 2.7, "gdp_deflator": 2.0, "wage_growth": 3.1},
]


def _fetch_real_inflation() -> list[dict] | None:
    """実データ取得フック。現状は未実装で常に None を返す。

    将来:
      - 総務省CPI: e-Stat API or CSV ダウンロード
      - 内閣府GDPデフレータ: SNA系列CSV
      - 厚労省毎月勤労統計: e-Stat API
    """
    return None


async def get_inflation() -> InflationResponse:
    """インフレ率3系列を返す。実データ取得失敗時はモックにフォールバック。"""
    today = date.today().isoformat()
    real = _fetch_real_inflation()
    raw = real if real is not None else _MOCK_INFLATION
    source = (
        "総務省CPI / 内閣府GDPデフレータ / 厚労省毎月勤労統計"
        if real is not None
        else "総務省CPI / 内閣府GDPデフレータ / 厚労省毎月勤労統計（モック）"
    )
    points = [InflationDataPoint(**d) for d in raw]
    return InflationResponse(
        data=points,
        source=source,
        boj_target=2.0,
        last_updated=today,
    )
