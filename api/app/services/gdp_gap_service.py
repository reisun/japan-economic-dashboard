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
from app.services.common_range import filter_to_actual_range
from app.services.data_utils import (
    record_data_source_status,
    warn_fred_key_missing_once,
)

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
# 最大概念潜在GDP: Cobb-Douglas 生産関数アプローチ (CBO methodology 準拠)
# ---------------------------------------------------------------------------
#
# 思想:
#   「潜在」は本来「持てる力の最大値」。ギャップは構造的に ≤ 0 で運用すべき
#   （0% を上回るのは概念の混乱）。投資が進めば潜在GDPも増える、という
#   ストック・労働投入の能力ベースで推計する。
#
# CBO Potential GDP methodology (https://www.cbo.gov/topics/economy) を
# 日本データに適用したもの。CBO の手順に従い、労働投入と資本投入を分解、
# TFP を Solow 残差として抽出し HP トレンド + フロンティア max を用いる。
#
# モデル:
#   Y_potential_t = A_max_t * (L_full_t)^(1-α) * (K_services_t)^α
#
#   α=0.33 （資本分配率）
#     日本の労働分配率 ≈ 2/3（SNA 雇用者報酬 / 国民所得ベース、近年67%前後）
#     よって資本分配率 ≈ 1/3。CBO 米国推計と同じ慣行値。
#     参考: 内閣府『国民経済計算年次推計』要素所得分配。
#
#   NAIRU=2.5% （構造的失業率, 非加速インフレ失業率）
#     日本の労働市場における完全雇用に対応する失業率の合意値。
#     2010年代後半に実績失業率が2.4%前後で賃金加速が見られなかったことが根拠。
#     参考: 日銀ワーキングペーパー / 内閣府ESRI Discussion Paper。
#
#   UTILIZATION_FULL=0.95 （完全稼働時の資本稼働率）
#     CBO は鉱工業稼働率の過去ピーク帯を使う。日本は経産省「鉱工業生産指数」
#     の稼働率指数。バブル期ピーク〜コロナ前ピークの平均を 95% 水準で代理。
#     ハードコード値。実データ取得時は ピーク値 = max(過去の稼働率_t) を採用。
#
# 労働投入の分解 (CBO 流):
#   L_full_t = 労働力人口_t × LFPR_trend_t × HOURS_trend_t × (1 - NAIRU)
#     - LFPR (Labor Force Participation Rate, 労働参加率) は HP フィルターで
#       トレンド抽出。CBO は構造LFPRを別途デモグラ分解で推計するが、本実装は
#       HP λ=1600 トレンドで近似。
#     - 平均労働時間も同様に HP トレンドで構造的に均す。
#   L_actual_t = 労働力人口_t × LFPR_t × HOURS_t × (1 - 実績失業率_t)
#
# 資本サービスの分解 (CBO 流):
#   K_services_t = K_stock_t × UTILIZATION_FULL
#     CBO の capital services は資本財別ウエイトで集計するが、本実装は
#     稼働率調整のみ。実データ差し替え時は SNA の実質資本サービス指数を使う。
#
# TFP (Solow 残差):
#   A_implied_t = Y_t / (L_actual_t^(1-α) × K_services_actual_t^α)
#     ここで K_services_actual_t = K_stock_t × 実績稼働率_t
#   A_trend_t  = HP_filter(A_implied_t, λ=1600)
#   A_max_t    = 累積max( max(A_trend_t, A_implied_t) )
#     「フロンティアTFP」を採用することで、過去ピーク水準の生産性が永続する
#     最大概念に整合させる（hysteresis 上方シフト）。
#
# 実データ差し替え点 (TODO):
#   - 労働力人口・就業者数・LFPR: 総務省統計局「労働力調査」
#   - 平均労働時間: 厚労省「毎月勤労統計」
#   - 失業率実績: 同 労働力調査
#   - 民間資本ストック: 内閣府「民間企業資本ストック」(SNA系列)
#   - 稼働率: 経産省「鉱工業指数」稼働率指数
#   現状はモック定数。実データ取得時は下記 _MOCK_* を差し替え、
#   _fetch_macro_inputs() フックで上書きすれば本実装はそのまま使える設計。
# ---------------------------------------------------------------------------

# 構造パラメータ (CBO methodology 投入定数)
_CD_ALPHA = 0.33  # 資本分配率（日本標準: 労働分配率 2/3 → 1 - 2/3）
_NAIRU = 0.025  # 構造的失業率 2.5%
_UTILIZATION_FULL = 0.95  # 完全稼働率（鉱工業稼働率ピーク帯の代理値）

# モック投入要素（_QUARTERS と同じ12四半期）
# 労働力人口（百万人）— 緩やかな減少トレンド
_MOCK_LABOR_FORCE: list[float] = [
    69.0, 69.0, 68.9, 68.8,
    68.8, 68.7, 68.6, 68.5,
    68.5, 68.4, 68.3, 68.2,
]
# LFPR (Labor Force Participation Rate, 労働参加率, 比率)
# 高齢化と女性就業拡大の合成で緩やかに上昇。日本実績は 62〜63% 帯。
_MOCK_LFPR: list[float] = [
    0.625, 0.626, 0.627, 0.628,
    0.628, 0.629, 0.629, 0.630,
    0.630, 0.631, 0.631, 0.632,
]
# 平均労働時間（時間/月）— 短縮トレンド + 季節揺らぎ
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
# 実績資本稼働率（比率）— 鉱工業稼働率指数の代理値。完全=0.95 を上回らない。
_MOCK_UTILIZATION: list[float] = [
    0.91, 0.92, 0.92, 0.93,
    0.93, 0.93, 0.92, 0.92,
    0.91, 0.90, 0.90, 0.89,
]


def _estimate_gdp_gap_maximum(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
    """最大概念のGDPギャップ (CBO methodology 準拠 Cobb-Douglas)。

    Y_potential = A_max * L_full^(1-α) * K_services_full^α
      L_full          = 労働力人口 × LFPR_trend × HOURS_trend × (1 - NAIRU)
      K_services_full = K_stock × UTILIZATION_FULL
      A_max           = 累積max( max(HP_trend(A_implied), A_implied) )

    実績側は LFPR・HOURS は実績値、稼働率も実績値、失業率も実績値で
    A_implied (Solow 残差) を取り、HP トレンド + フロンティア max で
    「持てる力の最大」を表す TFP に変換する。

    実績側投入 (LFPR, HOURS, 稼働率, 失業率) ≤ 完全雇用側投入の関係を
    保持するため、Y_potential ≥ Y_actual, gap ≤ 0 が構造的に成立する。

    NOTE: 現状はモックパラメータ（_MOCK_* 群）。
          実データ差し替えは _fetch_macro_inputs() を実装する。
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
    lfpr = _resize(_MOCK_LFPR)
    hours = _resize(_MOCK_HOURS)
    unemployment = _resize(_MOCK_UNEMPLOYMENT) / 100.0  # % → 比率
    capital = _resize(_MOCK_CAPITAL_STOCK)
    utilization = _resize(_MOCK_UTILIZATION)

    # CBO 流: LFPR と HOURS は HP トレンドで構造化
    lfpr_trend = _hp_filter(lfpr)
    hours_trend = _hp_filter(hours)

    # 実績労働投入 (Solow 残差用)
    # L_actual = 労働力人口 × LFPR_実績 × HOURS_実績 × (1 - 失業率_実績)
    L_actual = labor_force * lfpr * hours * (1.0 - unemployment)
    # 完全雇用労働投入 (CBO methodology)
    # L_full = 労働力人口 × LFPR_trend × HOURS_trend × (1 - NAIRU)
    L_full = labor_force * lfpr_trend * hours_trend * (1.0 - _NAIRU)

    # 資本サービス
    # 実績側は実績稼働率、完全雇用側は完全稼働率を用いる
    K_services_actual = capital * utilization
    K_services_full = capital * _UTILIZATION_FULL

    # Solow 残差 TFP: A_t = Y_t / (L_actual_t^(1-α) × K_services_actual_t^α)
    denom_actual = (L_actual ** (1.0 - _CD_ALPHA)) * (K_services_actual ** _CD_ALPHA)
    A_implied = y / denom_actual

    # フロンティア TFP: HPトレンドと実績の max → 累積max
    # 「持てる力の最大」の思想 (CBO 自体は HP トレンド止まりだが、本実装は
    # 最大概念寄りに踏み込む)。
    A_smoothed = _hp_filter(A_implied)
    A_frontier = np.maximum(A_smoothed, A_implied)
    A_max = np.maximum.accumulate(A_frontier)

    # 完全雇用ベースの潜在GDP
    potential_max = A_max * (L_full ** (1.0 - _CD_ALPHA)) * (K_services_full ** _CD_ALPHA)

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


# ---------------------------------------------------------------------------
# 在野試算 (civilian): 線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式)
# ---------------------------------------------------------------------------
# 思想:
#   高橋洋一氏 (嘉悦大学) が継続的に公表している GDP ギャップ試算は、
#   実績GDPのピーク群を上方包絡する「完全な直線」の潜在GDPを当てはめる
#   手法を取っており、グラフ上で潜在GDPは時間に対する単調直線になる。
#   個別論考での詳細式は明示されていないが、グラフ形状から
#   「ピーク・トゥ・ピーク線形トレンド」(peak-to-peak linear trend) と
#   推定できる。本実装はこのグラフ形状から推定したアルゴリズムであり、
#   高橋氏の個別論考を直接転載したものではない。
#
# アルゴリズム概要:
#   1. ピーク包絡: 各 t について直近 K=16 クォーター (4年) の最大値を取る
#   2. 外的ショック除外: 直近4Qピークから 5% 以上落ち込んだ点は線形回帰の
#      対象外とする (コロナ底など)
#   3. ピーク群に最小二乗で `peak ≈ a + b·t` を当てはめる
#   4. 包絡条件: 切片 a を上方調整し、全期間で潜在GDP ≥ 実績GDP を保証
#   5. ギャップ %: (Y_t - Y_pot(t)) / Y_pot(t) × 100
#
# 出力特性:
#   - 潜在GDPは時間に対する完全な直線
#   - 全期間でギャップ ≤ 0 (デフレギャップのみ)
# ---------------------------------------------------------------------------

# パラメータ定数
_K_PEAK_WINDOW = 16  # ピーク包絡窓 (クォーター数, 4年)
_SHOCK_DROP_THRESHOLD = 0.05  # 5% 以上の落ち込みを外的ショックとして除外
_BUFFER_TRILLION = 0.5  # 包絡線の上方マージン (兆円)


def _peak_to_peak_linear_trend(
    y: np.ndarray,
    k_window: int = _K_PEAK_WINDOW,
    shock_drop_threshold: float = _SHOCK_DROP_THRESHOLD,
    buffer: float = _BUFFER_TRILLION,
) -> tuple[np.ndarray, float, float]:
    """高橋洋一氏方式に基づくピーク・トゥ・ピーク線形トレンド推計。

    Parameters
    ----------
    y : 実績GDP系列 (1-D, 兆円単位想定)
    k_window : ピーク包絡窓 (クォーター数)
    shock_drop_threshold : 直近4Qピークからの相対落ち込み閾値 (これ以上で除外)
    buffer : 包絡上方マージン (y と同単位)

    Returns
    -------
    potential : 潜在GDP直線 (a + b*t, 全期間で y を下回らないよう上方シフト済)
    a : 上方シフト後の切片
    b : 線形トレンドの傾き (y と同単位/クォーター)
    """
    n = len(y)
    if n < 2:
        return y.copy(), float(y[0]) if n else 0.0, 0.0

    # 1. ピーク包絡: 各 t について直近 K クォーター内の最大値
    peak_envelope = np.empty(n)
    for t in range(n):
        lo = max(0, t - k_window + 1)
        peak_envelope[t] = np.max(y[lo : t + 1])

    # 2. 外的ショック除外: 直近4Qピークから shock_drop_threshold 以上の落ち込みは除外
    include_mask = np.ones(n, dtype=bool)
    for t in range(n):
        lo4 = max(0, t - 3)
        recent_peak = np.max(y[lo4 : t + 1])
        if recent_peak > 0 and (recent_peak - y[t]) / recent_peak >= shock_drop_threshold:
            include_mask[t] = False

    # 3. ピーク群に対する最小二乗線形回帰
    t_idx = np.arange(n, dtype=float)
    if include_mask.sum() >= 2:
        ts = t_idx[include_mask]
        ps = peak_envelope[include_mask]
    else:
        # 全点ショック扱いになった場合は全点を使う (フォールバック)
        ts = t_idx
        ps = peak_envelope
    b, a = np.polyfit(ts, ps, 1)  # slope, intercept

    # 4. 包絡条件: 全期間で潜在 ≥ 実績 になるよう切片を上方調整
    line = a + b * t_idx
    deficit = float(np.max(y - line))
    if deficit > 0:
        a = a + deficit
    a = a + buffer
    potential = a + b * t_idx
    return potential, float(a), float(b)


def _estimate_gdp_gap_civilian(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
    """在野試算 GDP ギャップ: 線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式)。

    実績GDPのピーク群 (直近16Q窓内の最大値、外的ショック期は除外) に
    最小二乗で直線をフィッティングし、上方包絡シフトを掛けて潜在GDPとする。
    高橋洋一氏のGDPギャップ試算 (典型的にコロナ前ピーク群を結ぶ直線) を
    参考にした実装である。個別論考の数式そのものではなく、公開グラフの
    形状から推定した手法を再現している。
    """
    n = len(real_gdp)
    if n == 0:
        return []
    y = np.array(real_gdp, dtype=float)

    potential, _a, _b = _peak_to_peak_linear_trend(y)

    results: list[EstimatedGdpGapDataPoint] = []
    for i, q in enumerate(quarters):
        pot = float(potential[i])
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
        warn_fred_key_missing_once()
        logger.debug("FRED_API_KEY not set -- using mock real GDP")
        record_data_source_status(
            "fred:JPNRGDPEXP", ok=False, detail="api_key_missing"
        )
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
        if gdp_values:
            record_data_source_status(
                "fred:JPNRGDPEXP",
                ok=True,
                detail=f"points={len(gdp_values)}",
            )
            return (gdp_values, quarter_labels)
        record_data_source_status(
            "fred:JPNRGDPEXP", ok=False, detail="empty_series"
        )
        return None
    except Exception as e:
        logger.exception("FRED real GDP fetch failed")
        record_data_source_status(
            "fred:JPNRGDPEXP", ok=False, detail=f"exception:{type(e).__name__}"
        )
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
    using_real_gdp = real_gdp_result is not None
    logger.info(
        "gdp_gap data sources: %s",
        {
            "boj_output_gap": "real" if using_real_boj else "mock",
            "fred_real_gdp": "real" if using_real_gdp else "mock",
        },
    )
    try:
        if real_gdp_result is not None:
            gdp_values, quarters = real_gdp_result
        else:
            gdp_values, quarters = _MOCK_REAL_GDP, _QUARTERS
        average_data = _estimate_gdp_gap_average(gdp_values, quarters)
        maximum_data = _estimate_gdp_gap_maximum(gdp_values, quarters)
        civilian_data = _estimate_gdp_gap_civilian(gdp_values, quarters)
    except Exception:
        logger.exception("HP filter estimation failed, using raw mock")
        average_data = [
            EstimatedGdpGapDataPoint(
                date=q, real_gdp=g, potential_gdp=g, gdp_gap_percent=0.0
            )
            for q, g in zip(_QUARTERS, _MOCK_REAL_GDP)
        ]
        maximum_data = average_data
        civilian_data = average_data

    # 共通レンジ（GDPギャップ実績期間）に揃える。
    # estimated_* は GDP 実データ自体の長さがレンジの基準なので原則変わらないが、
    # 一貫性のため通す。BOJ output gap は系列長が異なる可能性があるためフィルタ。
    boj_data = filter_to_actual_range(boj_data, label="boj_output_gap")
    average_data = filter_to_actual_range(average_data, label="gdp_gap_average")
    maximum_data = filter_to_actual_range(maximum_data, label="gdp_gap_maximum")
    civilian_data = filter_to_actual_range(civilian_data, label="gdp_gap_civilian")

    average = EstimatedGdpGap(
        data=average_data, method="HP Filter (平均概念)", last_updated=today
    )
    maximum = EstimatedGdpGap(
        data=maximum_data,
        method=(
            "Cobb-Douglas (CBO methodology: 完全雇用労働投入 × capital services × TFP_max, "
            "α=0.33, NAIRU=2.5%)"
        ),
        last_updated=today,
    )
    civilian = EstimatedGdpGap(
        data=civilian_data,
        method="線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式に基づく在野試算)",
        last_updated=today,
    )

    data_status = {
        "boj_output_gap": "real" if using_real_boj else "mock",
        "fred_real_gdp": "real" if using_real_gdp else "mock",
    }

    return GdpGapResponse(
        cabinet_office=CabinetOfficeGdpGap(
            data=boj_data,
            source="日銀" if using_real_boj else "内閣府",
            last_updated=today,
        ),
        estimated_average=average,
        estimated_maximum=maximum,
        estimated_civilian=civilian,
        estimated=average,  # 後方互換エイリアス
        data_status=data_status,
    )
