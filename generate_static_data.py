#!/usr/bin/env python3
"""Generate static JSON data files for GitHub Pages deployment.

Reproduces the backend mock data and HP filter calculations
without requiring numpy/scipy/pydantic.
"""

import json
import os
import re
from datetime import datetime, timedelta

OUTPUT_DIRS = [
    os.path.join(os.path.dirname(__file__), "web", "public", "api", "v1"),
    os.path.join(os.path.dirname(__file__), "web", "dist", "api", "v1"),
]

# ---------------------------------------------------------------------------
# HP Filter (pure Python implementation)
# ---------------------------------------------------------------------------

def _solve_linear_system(A, b):
    """Solve Ax = b using Gaussian elimination with partial pivoting (pure Python)."""
    n = len(b)
    # Augmented matrix
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        # Partial pivoting
        max_row = col
        for row in range(col + 1, n):
            if abs(M[row][col]) > abs(M[max_row][col]):
                max_row = row
        M[col], M[max_row] = M[max_row], M[col]

        pivot = M[col][col]
        if abs(pivot) < 1e-12:
            continue

        for row in range(col + 1, n):
            factor = M[row][col] / pivot
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = M[i][n]
        for j in range(i + 1, n):
            x[i] -= M[i][j] * x[j]
        if abs(M[i][i]) > 1e-12:
            x[i] /= M[i][i]

    return x


def hp_filter(y, lamb=1600.0):
    """Hodrick-Prescott filter: extract trend (potential GDP)."""
    n = len(y)
    if n < 4:
        return y[:]

    # Build the (I + lambda * K'K) matrix where K is second-difference operator
    # Diagonal elements
    diag = [0.0] * n
    diag[0] = 1 + lamb
    diag[1] = 1 + 5 * lamb
    for i in range(2, n - 2):
        diag[i] = 1 + 6 * lamb
    diag[n - 2] = 1 + 5 * lamb
    diag[n - 1] = 1 + lamb

    # Off-diagonal +/-1
    off1 = [0.0] * (n - 1)
    off1[0] = -2 * lamb
    for i in range(1, n - 2):
        off1[i] = -4 * lamb
    off1[n - 2] = -2 * lamb

    # Off-diagonal +/-2
    off2 = [lamb] * (n - 2)

    # Build full matrix
    A = [[0.0] * n for _ in range(n)]
    for i in range(n):
        A[i][i] = diag[i]
    for i in range(n - 1):
        A[i][i + 1] = off1[i]
        A[i + 1][i] = off1[i]
    for i in range(n - 2):
        A[i][i + 2] = off2[i]
        A[i + 2][i] = off2[i]

    trend = _solve_linear_system(A, list(y))
    return trend


# ---------------------------------------------------------------------------
# GDP Gap data
# ---------------------------------------------------------------------------

MOCK_CABINET_DATA = [
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

MOCK_REAL_GDP = [
    535.0, 537.0, 539.5, 542.0,
    544.0, 546.0, 548.5, 551.0,
    549.0, 547.0, 545.0, 543.0,
]

QUARTERS = [d["date"] for d in MOCK_CABINET_DATA]


# ---------------------------------------------------------------------------
# 最大概念潜在GDP: CBO methodology 準拠 Cobb-Douglas
# ---------------------------------------------------------------------------
# Y_potential_t = A_max_t * (L_full_t)^(1-α) * (K_services_full_t)^α
#   α=0.33                  資本分配率（日本: 労働分配率2/3 → 1-2/3）
#   NAIRU=2.5%              構造的失業率（日本標準）
#   UTILIZATION_FULL=0.95   完全稼働率（鉱工業稼働率ピーク帯の代理値）
#
# 労働投入の分解 (CBO 流):
#   L_full = 労働力人口 × LFPR_trend × HOURS_trend × (1 - NAIRU)
#   LFPR と HOURS は HP λ=1600 でトレンド抽出
# 資本サービス:
#   K_services_full = K_stock × UTILIZATION_FULL
# TFP:
#   A_implied = Y / (L_actual^(1-α) × K_services_actual^α)
#   A_max = 累積max( max(HP_trend(A_implied), A_implied) )
#
# 実データ差し替え点:
#   - 労働力人口/LFPR/失業率: 総務省統計局「労働力調査」
#   - 平均労働時間: 厚労省「毎月勤労統計」
#   - 民間資本ストック: 内閣府SNA系列
#   - 稼働率: 経産省「鉱工業指数」稼働率指数
# ---------------------------------------------------------------------------

_CD_ALPHA = 0.33
_NAIRU = 0.025
_UTILIZATION_FULL = 0.95

MOCK_LABOR_FORCE = [
    69.0, 69.0, 68.9, 68.8,
    68.8, 68.7, 68.6, 68.5,
    68.5, 68.4, 68.3, 68.2,
]
# LFPR (労働参加率, 比率): 高齢化と女性就業拡大の合成で緩やかに上昇
MOCK_LFPR = [
    0.625, 0.626, 0.627, 0.628,
    0.628, 0.629, 0.629, 0.630,
    0.630, 0.631, 0.631, 0.632,
]
MOCK_HOURS = [
    138.0, 138.5, 138.8, 139.0,
    139.2, 139.5, 139.8, 140.0,
    139.8, 139.5, 139.2, 139.0,
]
MOCK_UNEMPLOYMENT = [
    2.7, 2.6, 2.6, 2.5,
    2.6, 2.6, 2.5, 2.5,
    2.6, 2.7, 2.7, 2.8,
]
MOCK_CAPITAL_STOCK = [
    1860.0, 1865.0, 1870.0, 1876.0,
    1882.0, 1888.0, 1895.0, 1902.0,
    1908.0, 1914.0, 1920.0, 1926.0,
]
# 実績資本稼働率（比率, 鉱工業稼働率指数の代理）
MOCK_UTILIZATION = [
    0.91, 0.92, 0.92, 0.93,
    0.93, 0.93, 0.92, 0.92,
    0.91, 0.90, 0.90, 0.89,
]


def _estimate_average(real_gdp, quarters):
    potential = hp_filter(real_gdp, 1600.0)
    out = []
    for i, q in enumerate(quarters):
        gap_pct = round((real_gdp[i] - potential[i]) / potential[i] * 100, 2)
        out.append({
            "date": q,
            "real_gdp": round(real_gdp[i], 1),
            "potential_gdp": round(potential[i], 1),
            "gdp_gap_percent": gap_pct,
        })
    return out


def _estimate_maximum(real_gdp, quarters):
    """最大概念: CBO methodology 準拠 Cobb-Douglas。
    L_full = 労働力人口 × LFPR_trend × HOURS_trend × (1-NAIRU)
    K_services = K_stock × UTILIZATION_FULL
    A_max = 累積max(max(HP_trend(A_implied), A_implied))
    実績投入 ≤ 完全雇用投入 のため gap ≤ 0 が構造的に成立。"""
    n = len(real_gdp)

    def resize(seq):
        if len(seq) == n:
            return list(seq)
        if len(seq) > n:
            return list(seq[-n:])
        return [seq[0]] * (n - len(seq)) + list(seq)

    labor = resize(MOCK_LABOR_FORCE)
    lfpr = resize(MOCK_LFPR)
    hours = resize(MOCK_HOURS)
    unemp = [u / 100.0 for u in resize(MOCK_UNEMPLOYMENT)]
    capital = resize(MOCK_CAPITAL_STOCK)
    utilization = resize(MOCK_UTILIZATION)

    # CBO 流: LFPR と HOURS は HP トレンドで構造化
    lfpr_trend = hp_filter(lfpr, 1600.0)
    hours_trend = hp_filter(hours, 1600.0)

    L_actual = [labor[i] * lfpr[i] * hours[i] * (1.0 - unemp[i]) for i in range(n)]
    L_full = [
        labor[i] * lfpr_trend[i] * hours_trend[i] * (1.0 - _NAIRU)
        for i in range(n)
    ]

    K_services_actual = [capital[i] * utilization[i] for i in range(n)]
    K_services_full = [capital[i] * _UTILIZATION_FULL for i in range(n)]

    A_implied = [
        real_gdp[i] / ((L_actual[i] ** (1.0 - _CD_ALPHA)) * (K_services_actual[i] ** _CD_ALPHA))
        for i in range(n)
    ]
    A_smoothed = hp_filter(A_implied, 1600.0)
    # フロンティアTFP: HPトレンドと実績TFPの max の累積max（hysteresis 上方シフト）
    A_frontier = [max(A_smoothed[i], A_implied[i]) for i in range(n)]
    A_max = []
    running = A_frontier[0]
    for v in A_frontier:
        if v > running:
            running = v
        A_max.append(running)

    out = []
    for i, q in enumerate(quarters):
        pot = A_max[i] * (L_full[i] ** (1.0 - _CD_ALPHA)) * (K_services_full[i] ** _CD_ALPHA)
        if pot <= 0:
            pot = real_gdp[i]
        gap_pct = round((real_gdp[i] - pot) / pot * 100, 2)
        out.append({
            "date": q,
            "real_gdp": round(real_gdp[i], 1),
            "potential_gdp": round(pot, 1),
            "gdp_gap_percent": gap_pct,
        })
    return out


# ---------------------------------------------------------------------------
# 在野試算 (civilian): 線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式)
# ---------------------------------------------------------------------------
# 高橋洋一氏のGDPギャップ試算 (典型的にコロナ前ピーク群を結ぶ直線) を
# 参考にした実装。グラフ形状から推定したアルゴリズムであり、個別論考の
# 数式そのものではない。詳細は api/app/services/gdp_gap_service.py を参照。
K_PEAK_WINDOW = 16  # ピーク包絡窓 (クォーター数, 4年)
SHOCK_DROP_THRESHOLD = 0.05  # 5% 以上の落ち込みを外的ショックとして除外
BUFFER_TRILLION = 0.5  # 包絡上方マージン (兆円)


def _peak_to_peak_linear_trend(y, k_window=K_PEAK_WINDOW,
                               shock_drop_threshold=SHOCK_DROP_THRESHOLD,
                               buffer=BUFFER_TRILLION):
    """高橋洋一氏方式: ピーク群への線形回帰 + 上方包絡シフト。

    Returns (potential_list, intercept_a, slope_b).
    """
    n = len(y)
    if n == 0:
        return [], 0.0, 0.0
    if n == 1:
        return [float(y[0])], float(y[0]), 0.0

    # 1. ピーク包絡
    peak_envelope = []
    for t in range(n):
        lo = max(0, t - k_window + 1)
        peak_envelope.append(max(y[lo:t + 1]))

    # 2. 外的ショック除外 (直近4Qピークから shock_drop_threshold 以上の落ち込み)
    include = []
    for t in range(n):
        lo4 = max(0, t - 3)
        recent_peak = max(y[lo4:t + 1])
        drop = (recent_peak - y[t]) / recent_peak if recent_peak > 0 else 0.0
        include.append(drop < shock_drop_threshold)

    # 3. ピーク群に最小二乗線形回帰
    ts = [float(t) for t, inc in enumerate(include) if inc]
    ps = [peak_envelope[t] for t, inc in enumerate(include) if inc]
    if len(ts) < 2:
        ts = [float(t) for t in range(n)]
        ps = list(peak_envelope)

    m = len(ts)
    sum_t = sum(ts)
    sum_p = sum(ps)
    sum_tt = sum(t * t for t in ts)
    sum_tp = sum(ts[i] * ps[i] for i in range(m))
    denom = m * sum_tt - sum_t * sum_t
    if denom == 0:
        b = 0.0
        a = sum_p / m
    else:
        b = (m * sum_tp - sum_t * sum_p) / denom
        a = (sum_p - b * sum_t) / m

    # 4. 包絡条件: 全期間で潜在 ≥ 実績 を保証
    line = [a + b * t for t in range(n)]
    deficit = max(y[t] - line[t] for t in range(n))
    if deficit > 0:
        a = a + deficit
    a = a + buffer
    potential = [a + b * t for t in range(n)]
    return potential, a, b


def _estimate_civilian(real_gdp, quarters):
    """在野試算: 線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式)。"""
    n = len(real_gdp)
    if n == 0:
        return []
    y = [float(v) for v in real_gdp]
    potential, _a, _b = _peak_to_peak_linear_trend(y)

    out = []
    for i, q in enumerate(quarters):
        pot = potential[i]
        if pot <= 0:
            pot = y[i]
        gap_pct = (y[i] - pot) / pot * 100
        out.append({
            "date": q,
            "real_gdp": round(y[i], 1),
            "potential_gdp": round(pot, 1),
            "gdp_gap_percent": round(gap_pct, 2),
        })
    return out


def generate_gdp_gap():
    today = "2026-04-27"

    average_data = _estimate_average(MOCK_REAL_GDP, QUARTERS)
    maximum_data = _estimate_maximum(MOCK_REAL_GDP, QUARTERS)
    civilian_data = _estimate_civilian(MOCK_REAL_GDP, QUARTERS)

    average_block = {
        "data": average_data,
        "method": "HP Filter (平均概念)",
        "last_updated": today,
    }
    maximum_block = {
        "data": maximum_data,
        "method": (
            "Cobb-Douglas (CBO methodology: 完全雇用労働投入 × capital services × TFP_max, "
            "α=0.33, NAIRU=2.5%)"
        ),
        "last_updated": today,
    }
    civilian_block = {
        "data": civilian_data,
        "method": "線形ピーク・トゥ・ピーク・トレンド (高橋洋一氏方式に基づく在野試算)",
        "last_updated": today,
    }

    return {
        "cabinet_office": {
            "data": MOCK_CABINET_DATA,
            "source": "内閣府",
            "last_updated": today,
        },
        "estimated_average": average_block,
        "estimated_maximum": maximum_block,
        "estimated_civilian": civilian_block,
        # 後方互換エイリアス
        "estimated": average_block,
    }


# ---------------------------------------------------------------------------
# Fund Demand data
# ---------------------------------------------------------------------------

def _fetch_boj_flow_of_funds_static():
    """BOJ 時系列データ検索サイトの ZIP を取得し、部門別純貸出を返す。

    失敗時 None。pure-Python (urllib + zipfile + csv) のみ使用。
    """
    try:
        import csv as _csv
        import io as _io
        import urllib.request
        import zipfile as _zip

        url = "https://www.stat-search.boj.or.jp/info/fof2_en.zip"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (japan-economic-dashboard static)"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            buf = resp.read()
        sectors = {
            "households":   "FOF_FFAF430L700",
            "corporations": "FOF_FFAF410L700",
            "government":   "FOF_FFAF420L700",
        }
        target = set(sectors.values())
        with _zip.ZipFile(_io.BytesIO(buf)) as zf:
            csv_bytes = zf.read("ff_dl_fof_quarterly_en.csv")
        text = csv_bytes.decode("utf-8-sig", errors="replace")
        rows = list(_csv.reader(_io.StringIO(text)))
        if not rows:
            return None
        header = rows[0]
        period_cols = []
        for i in range(3, len(header)):
            s = header[i].strip()
            if len(s) == 6 and s.isdigit():
                period_cols.append((i, int(s[:4]), int(s[4:])))
        sid_row = {r[0].strip(): r for r in rows[1:] if r and r[0].strip() in target}
        out = []
        order = {"households": 0, "corporations": 1, "government": 2}
        for sector, sid in sectors.items():
            row = sid_row.get(sid)
            if not row:
                return None
            for col, year, q in period_cols:
                if col >= len(row):
                    continue
                cell = row[col].strip()
                if not cell:
                    continue
                try:
                    v = float(cell)
                except ValueError:
                    continue
                out.append({
                    "date": f"{year}-Q{q}",
                    "sector": sector,
                    "net_lending": round(v / 10000.0, 1),
                })
        out.sort(key=lambda p: (p["date"], order.get(p["sector"], 99)))
        return out or None
    except Exception as e:
        print(f"[generate_static_data] BOJ FOF fetch failed: {e}")
        return None


def generate_fund_demand():
    quarters = [
        "2022-Q1", "2022-Q2", "2022-Q3", "2022-Q4",
        "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
        "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4",
    ]

    real_flow = _fetch_boj_flow_of_funds_static()
    if real_flow:
        print(f"[generate_static_data] flow_of_funds: real ({len(real_flow)} points from BOJ stat-search)")
        flow_data = real_flow
    else:
        print("[generate_static_data] flow_of_funds: mock (BOJ fetch failed)")
        flow_data = []
        for q in quarters:
            flow_data.extend([
                {"date": q, "sector": "households",   "net_lending": round(12.0 + (hash(q) % 10) * 0.5, 1)},
                {"date": q, "sector": "corporations", "net_lending": round(-4.0 + (hash(q) % 6) * 0.3, 1)},
                {"date": q, "sector": "government",   "net_lending": round(-18.0 - (hash(q) % 8) * 0.4, 1)},
            ])

    bank_lending = [
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

    return {
        "flow_of_funds": {
            "data": flow_data,
            "source": "日銀資金循環統計",
            "unit": "兆円",
        },
        "bank_lending": {
            "data": bank_lending,
            "source": "日銀貸出統計",
            "unit": "兆円",
        },
    }


# ---------------------------------------------------------------------------
# Rates data
# ---------------------------------------------------------------------------

def generate_rates():
    dates = [
        (datetime(2024, 1, 1) + timedelta(days=30 * i)).strftime("%Y-%m-%d")
        for i in range(12)
    ]

    fred_rates = [
        {"date": d, "us_10y_yield": round(4.2 + i * 0.05, 2), "fed_funds_rate": round(5.25 - i * 0.04, 2)}
        for i, d in enumerate(dates)
    ]

    boj_rates = [
        {"date": d, "policy_rate": round(-0.10 + i * 0.02, 2), "jgb_10y_yield": round(0.60 + i * 0.03, 2)}
        for i, d in enumerate(dates)
    ]

    fred_fx = [
        {"date": d, "usdjpy": round(148.0 + i * 0.5, 1)} for i, d in enumerate(dates)
    ]

    return {
        "interest_rates": {
            "fred": fred_rates,
            "boj": boj_rates,
        },
        "exchange_rates": {
            "fred": fred_fx,
        },
    }


# ---------------------------------------------------------------------------
# Prediction data (IS-LM model)
# ---------------------------------------------------------------------------

FISCAL_MULTIPLIER = 1.0
MONEY_DEMAND_ELASTICITY = 0.5
INVESTMENT_SENSITIVITY = 0.3
NOMINAL_GDP = 560.0
BASELINE_JGB_10Y = 0.85
BASELINE_USDJPY = 150.0
UIP_SENSITIVITY = 2.0
PHILLIPS_CURVE_SLOPE = 0.3
BASELINE_INFLATION_FALLBACK = 2.0
PREDICTION_QUARTERS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]


def generate_prediction(method="maximum"):
    # Get GDP gap based on method
    gdp_gap_data = generate_gdp_gap()
    if method == "cabinet_office":
        gap_pct = gdp_gap_data["cabinet_office"]["data"][-1]["gdp_gap_percent"]
    elif method == "average":
        gap_pct = gdp_gap_data["estimated_average"]["data"][-1]["gdp_gap_percent"]
    elif method == "civilian":
        gap_pct = gdp_gap_data["estimated_civilian"]["data"][-1]["gdp_gap_percent"]
    else:  # maximum (default)
        gap_pct = gdp_gap_data["estimated_maximum"]["data"][-1]["gdp_gap_percent"]
    gap_trillion = round(gap_pct / 100.0 * NOMINAL_GDP, 1)

    # Required fiscal spending (符号付き; マイナス需給ギャップ → 拡張、プラス → 引き締め)
    required_spending = -gap_trillion / FISCAL_MULTIPLIER

    # IS-LM impact calculation
    total_dr = (
        required_spending
        * FISCAL_MULTIPLIER
        * MONEY_DEMAND_ELASTICITY
        / (INVESTMENT_SENSITIVITY + MONEY_DEMAND_ELASTICITY)
        / NOMINAL_GDP
        * 100
    )

    phase_in = [0.0, 0.33, 0.67, 1.0]

    # GDP impact: fiscal spending effect on GDP (% change from baseline)
    total_gdp_change_pct = required_spending * FISCAL_MULTIPLIER / NOMINAL_GDP * 100

    # Baseline inflation from mock data
    baseline_inflation = MOCK_INFLATION[-1]["cpi_core_core"] if MOCK_INFLATION else BASELINE_INFLATION_FALLBACK

    interest_predictions = []
    exchange_predictions = []
    gdp_impact_predictions = []
    inflation_predictions = []

    for i, frac in enumerate(phase_in):
        dr = total_dr * frac
        r = round(BASELINE_JGB_10Y + dr, 2)
        fx = round(BASELINE_USDJPY - dr * UIP_SENSITIVITY, 1)

        interest_predictions.append({
            "date": PREDICTION_QUARTERS[i],
            "predicted_jgb_10y": r,
            "type": "actual" if i == 0 else "prediction",
        })
        exchange_predictions.append({
            "date": PREDICTION_QUARTERS[i],
            "predicted_usdjpy": fx,
            "type": "actual" if i == 0 else "prediction",
        })
        gdp_impact_predictions.append({
            "date": PREDICTION_QUARTERS[i],
            "predicted_gdp_change_percent": round(total_gdp_change_pct * frac, 4),
            "type": "actual" if i == 0 else "prediction",
        })
        inflation_predictions.append({
            "date": PREDICTION_QUARTERS[i],
            "predicted_inflation_percent": round(
                baseline_inflation + PHILLIPS_CURVE_SLOPE * (gap_pct + total_gdp_change_pct * frac),
                2,
            ),
            "type": "actual" if i == 0 else "prediction",
        })

    return {
        "current_gap": {
            "gdp_gap_percent": gap_pct,
            "gdp_gap_trillion_yen": gap_trillion,
        },
        "required_fiscal_spending": {
            "amount_trillion_yen": round(required_spending, 1),
            "multiplier": FISCAL_MULTIPLIER,
            "note": (
                "デフレギャップ解消に必要な財政支出"
                if required_spending >= 0
                else "インフレギャップ抑制に必要な財政引き締め"
            ),
            "gap_fill_percent": 100.0,
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "gdp_impact": gdp_impact_predictions,
            "inflation_prediction": inflation_predictions,
            "model": "IS-LM",
            "engine": "is_lm",
            "assumptions": {
                "money_demand_elasticity": MONEY_DEMAND_ELASTICITY,
                "investment_sensitivity": INVESTMENT_SENSITIVITY,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
                "phillips_curve_slope": PHILLIPS_CURVE_SLOPE,
                "baseline_inflation": baseline_inflation,
                "multiplier_decay_rate": None,
            },
        },
    }


# ---------------------------------------------------------------------------
# 統計モデル予測 (VAR(1) / AR(1)) — pure-Python 版
# ---------------------------------------------------------------------------
# 静的JSON用に numpy なしで OLS-VAR(1) と AR(1) を実装する。
# 内生変数: GDPギャップ, JGB10y, USDJPY, CPIコアコア（4変数四半期パネル）
# 入力データはこのスクリプト内の MOCK_REAL_GDP / MOCK_INFLATION / generate_rates から
# 共通期間で取得した近似値を使う。

VAR_NOMINAL_GDP = 560.0
VAR_PREDICTION_STEPS = 8
VARIABLE_NAMES_STATIC = ["gdp_gap", "jgb_10y", "usdjpy", "cpi_core_core"]


def _matmul(A, B):
    n = len(A)
    m = len(B[0]) if B and B[0] else 0
    p = len(B)
    out = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for k in range(p):
            aik = A[i][k]
            for j in range(m):
                out[i][j] += aik * B[k][j]
    return out


def _matvec(A, x):
    return [sum(A[i][j] * x[j] for j in range(len(x))) for i in range(len(A))]


def _transpose(A):
    return [list(col) for col in zip(*A)]


def _eye(n, scale=1.0):
    return [[scale if i == j else 0.0 for j in range(n)] for i in range(n)]


def _solve_matrix(A, B):
    """Solve A X = B  (B can be list-of-rows). 多列右辺対応。"""
    n = len(B)
    m = len(B[0])
    # Augment
    M = [list(A[i]) + list(B[i]) for i in range(n)]
    for col in range(n):
        max_row = col
        for r in range(col + 1, n):
            if abs(M[r][col]) > abs(M[max_row][col]):
                max_row = r
        M[col], M[max_row] = M[max_row], M[col]
        pivot = M[col][col]
        if abs(pivot) < 1e-12:
            continue
        for r in range(col + 1, n):
            factor = M[r][col] / pivot
            for j in range(col, n + m):
                M[r][j] -= factor * M[col][j]
    X = [[0.0] * m for _ in range(n)]
    for i in range(n - 1, -1, -1):
        for j in range(m):
            s = M[i][n + j]
            for k in range(i + 1, n):
                s -= M[i][k] * X[k][j]
            if abs(M[i][i]) > 1e-12:
                X[i][j] = s / M[i][i]
    return X


def _fit_var1(Y):
    """Y: list of (k,) rows. Returns (c (k,), A (k,k))."""
    T = len(Y)
    k = len(Y[0])
    if T < 3:
        return [0.0] * k, _eye(k, 0.0)
    # X[(T-1) x (k+1)] = [1, Y_{t-1}], target Yt[t] = Y_{t}
    X = [[1.0] + list(Y[t - 1]) for t in range(1, T)]
    Yt = [list(Y[t]) for t in range(1, T)]
    Xt = _transpose(X)
    XtX = _matmul(Xt, X)
    # 微小リッジ
    for i in range(len(XtX)):
        XtX[i][i] += 1e-8
    XtY = _matmul(Xt, Yt)
    B = _solve_matrix(XtX, XtY)  # (k+1, k)
    c = list(B[0])
    A = [[B[1 + i][j] for i in range(k)] for j in range(k)]  # 転置: A[j][i] = coef of var i in eq j
    # 安定化: 最大固有値推定が困難なので、行ごと最大絶対値で大雑把に縮小
    # max_abs_row = max(sum(|A[i][j]|) for i)
    row_norm = max(sum(abs(v) for v in row) for row in A)
    if row_norm > 0.85:
        s = 0.85 / row_norm
        for i in range(k):
            for j in range(k):
                A[i][j] *= s
        # 長期均衡を保つよう c も再計算: y* = (I - A_orig)^-1 c_orig をまず近似
        # 簡略: データ平均を均衡にする
        mean_y = [sum(row[j] for row in Y) / T for j in range(k)]
        I_minus_As = [[(1.0 if i == j else 0.0) - A[i][j] for j in range(k)] for i in range(k)]
        c = _matvec(I_minus_As, mean_y)
    return c, A


def _forecast_var1(y_last, c, A, n_steps):
    out = []
    cur = list(y_last)
    for _ in range(n_steps):
        nxt = [c[i] + sum(A[i][j] * cur[j] for j in range(len(cur))) for i in range(len(c))]
        out.append(nxt)
        cur = nxt
    return out


def _irf_var1(A, n_steps, shock_vec):
    out = [list(shock_vec)]
    cur = list(shock_vec)
    for _ in range(n_steps):
        nxt = [sum(A[i][j] * cur[j] for j in range(len(cur))) for i in range(len(cur))]
        out.append(nxt)
        cur = nxt
    return out


def _fit_ar1_static(y):
    n = len(y)
    if n < 3:
        return float(y[-1] if y else 0.0), 0.0
    # OLS: y_t = c + phi y_{t-1}
    sx = sum(y[:-1])
    sy = sum(y[1:])
    sxx = sum(v * v for v in y[:-1])
    sxy = sum(y[t - 1] * y[t] for t in range(1, n))
    m = n - 1
    denom = m * sxx - sx * sx
    if abs(denom) < 1e-12:
        return float(y[-1]), 0.0
    phi = (m * sxy - sx * sy) / denom
    if not (phi == phi):  # NaN guard
        phi = 0.0
    if abs(phi) >= 0.95:
        phi = 0.95 if phi > 0 else -0.95
    mean_y = sum(y) / n
    c = (1.0 - phi) * mean_y
    return c, phi


def _forecast_ar1_static(y0, c, phi, n_steps):
    out = []
    cur = float(y0)
    for _ in range(n_steps):
        cur = c + phi * cur
        out.append(cur)
    return out


def _build_panel_static(method):
    """4変数（GDPギャップ/JGB/USDJPY/CPI）の四半期パネルを組み立てる。

    - GDPギャップ: method 別の generate_gdp_gap 系列を流用
    - JGB10y: generate_rates の boj 系列を四半期平均
    - USDJPY: generate_rates の fred 為替を四半期平均
    - CPIコアコア: MOCK_INFLATION
    """
    gdp = generate_gdp_gap()
    if method == "cabinet_office":
        gdp_data = gdp["cabinet_office"]["data"]
    elif method == "average":
        gdp_data = gdp["estimated_average"]["data"]
    elif method == "civilian":
        gdp_data = gdp["estimated_civilian"]["data"]
    else:
        gdp_data = gdp["estimated_maximum"]["data"]
    gdp_q = {p["date"]: float(p["gdp_gap_percent"]) for p in gdp_data}

    rates = generate_rates()

    def _to_q(label):
        m = re.match(r"^(\d{4})-(\d{2})", label)
        if not m:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{y}-Q{(mo - 1) // 3 + 1}"

    def _agg(points, key):
        bucket = {}
        for p in points:
            q = _to_q(p["date"])
            if q is None or p.get(key) is None:
                continue
            bucket.setdefault(q, []).append(float(p[key]))
        return {q: sum(vs) / len(vs) for q, vs in bucket.items() if vs}

    jgb_q = _agg(rates["interest_rates"]["boj"], "jgb_10y_yield")
    fx_q = _agg(rates["exchange_rates"]["fred"], "usdjpy")
    cpi_q = {p["date"]: float(p["cpi_core_core"]) for p in MOCK_INFLATION if p.get("cpi_core_core") is not None}

    common = sorted(
        set(gdp_q) & set(jgb_q) & set(fx_q) & set(cpi_q),
        key=lambda x: (int(x.split("-Q")[0]), int(x.split("-Q")[1])),
    )
    # 共通範囲が短い場合は ffill / bfill で揃える
    if len(common) < 6:
        all_q = sorted(
            set(gdp_q) | set(jgb_q) | set(fx_q) | set(cpi_q),
            key=lambda x: (int(x.split("-Q")[0]), int(x.split("-Q")[1])),
        )

        def fill(d):
            out = {}
            last = None
            for q in all_q:
                if q in d:
                    last = d[q]
                if last is not None:
                    out[q] = last
            last = None
            for q in reversed(all_q):
                if q in d and last is None:
                    last = d[q]
                if q not in out and last is not None:
                    out[q] = last
            return out

        gdp_q = fill(gdp_q)
        jgb_q = fill(jgb_q)
        fx_q = fill(fx_q)
        cpi_q = fill(cpi_q)
        common = [q for q in all_q if q in gdp_q and q in jgb_q and q in fx_q and q in cpi_q]

    Y = [[gdp_q[q], jgb_q[q], fx_q[q], cpi_q[q]] for q in common]
    return common, Y


def _next_quarter(qlabel):
    y, q = qlabel.split("-Q")
    y, q = int(y), int(q)
    q += 1
    if q > 4:
        q = 1
        y += 1
    return f"{y}-Q{q}"


def _build_future_quarters(last_q, n):
    out = []
    cur = last_q
    for _ in range(n):
        cur = _next_quarter(cur)
        out.append(cur)
    return out


def _build_spending_note(amount):
    return (
        "デフレギャップ解消に必要な財政支出"
        if amount >= 0
        else "インフレギャップ抑制に必要な財政引き締め"
    )


def generate_prediction_var(method="maximum"):
    quarters, Y = _build_panel_static(method)
    if not Y:
        return generate_prediction(method)
    T = len(Y)
    c, A = _fit_var1(Y)

    last_obs = Y[-1]
    gap_pct = last_obs[0]
    gap_trillion = round(gap_pct / 100.0 * VAR_NOMINAL_GDP, 1)
    required_spending = -gap_trillion / FISCAL_MULTIPLIER

    # 財政ショック → GDPギャップショック
    shock_gap_pct = required_spending / VAR_NOMINAL_GDP * 100.0 * FISCAL_MULTIPLIER
    shock_vec = [shock_gap_pct, 0.0, 0.0, 0.0]

    base_fc = _forecast_var1(last_obs, c, A, VAR_PREDICTION_STEPS)
    shock_resp = _irf_var1(A, VAR_PREDICTION_STEPS - 1, shock_vec)
    fc = [
        [base_fc[i][j] + shock_resp[i][j] for j in range(4)]
        for i in range(VAR_PREDICTION_STEPS)
    ]

    future_q = _build_future_quarters(quarters[-1], VAR_PREDICTION_STEPS)
    interest_predictions = [
        {"date": quarters[-1], "predicted_jgb_10y": round(last_obs[1], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_jgb_10y": round(fc[i][1], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    exchange_predictions = [
        {"date": quarters[-1], "predicted_usdjpy": round(last_obs[2], 1), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_usdjpy": round(fc[i][2], 1), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # GDP impact: difference between shocked and baseline GDP gap forecasts
    gdp_impact_predictions = [
        {"date": quarters[-1], "predicted_gdp_change_percent": 0.0, "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_gdp_change_percent": round(fc[i][0] - base_fc[i][0], 4), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # Inflation prediction: CPI core-core from shocked forecast
    inflation_predictions = [
        {"date": quarters[-1], "predicted_inflation_percent": round(last_obs[3], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_inflation_percent": round(fc[i][3], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # 単位ショック (+1兆円相当) IRF
    unit_shock = [1.0 / VAR_NOMINAL_GDP * 100.0, 0.0, 0.0, 0.0]
    irf = _irf_var1(A, VAR_PREDICTION_STEPS, unit_shock)
    irf_points = [
        {
            "horizon": h,
            "gdp_gap": round(irf[h][0], 4),
            "jgb_10y": round(irf[h][1], 4),
            "usdjpy": round(irf[h][2], 3),
            "cpi_core_core": round(irf[h][3], 4),
        }
        for h in range(VAR_PREDICTION_STEPS + 1)
    ]

    return {
        "current_gap": {
            "gdp_gap_percent": round(gap_pct, 2),
            "gdp_gap_trillion_yen": gap_trillion,
        },
        "required_fiscal_spending": {
            "amount_trillion_yen": round(required_spending, 1),
            "multiplier": FISCAL_MULTIPLIER,
            "note": _build_spending_note(required_spending),
            "gap_fill_percent": 100.0,
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "gdp_impact": gdp_impact_predictions,
            "inflation_prediction": inflation_predictions,
            "model": "VAR(1)",
            "engine": "var",
            "assumptions": {
                "lag_order": 1,
                "n_obs": T,
                "n_steps": VAR_PREDICTION_STEPS,
                "variables": VARIABLE_NAMES_STATIC,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
                "multiplier_decay_rate": None,
            },
            "irf": irf_points,
        },
    }


def generate_prediction_ar1(method="maximum"):
    quarters, Y = _build_panel_static(method)
    if not Y:
        return generate_prediction(method)
    T = len(Y)
    last_obs = Y[-1]
    gap_pct = last_obs[0]
    gap_trillion = round(gap_pct / 100.0 * VAR_NOMINAL_GDP, 1)
    required_spending = -gap_trillion / FISCAL_MULTIPLIER

    shock_gap_pct = required_spending / VAR_NOMINAL_GDP * 100.0 * FISCAL_MULTIPLIER
    last_shocked = list(last_obs)
    last_shocked[0] = last_obs[0] + shock_gap_pct

    # Baseline (no shock) forecast for GDP gap comparison
    fc_baseline = []
    for j in range(4):
        col = [Y[t][j] for t in range(T)]
        c, phi = _fit_ar1_static(col)
        fc_baseline.append(_forecast_ar1_static(last_obs[j], c, phi, VAR_PREDICTION_STEPS))

    # Shocked forecast
    fc = []
    for j in range(4):
        col = [Y[t][j] for t in range(T)]
        c, phi = _fit_ar1_static(col)
        fc.append(_forecast_ar1_static(last_shocked[j], c, phi, VAR_PREDICTION_STEPS))

    future_q = _build_future_quarters(quarters[-1], VAR_PREDICTION_STEPS)
    interest_predictions = [
        {"date": quarters[-1], "predicted_jgb_10y": round(last_obs[1], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_jgb_10y": round(fc[1][i], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    exchange_predictions = [
        {"date": quarters[-1], "predicted_usdjpy": round(last_obs[2], 1), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_usdjpy": round(fc[2][i], 1), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # GDP impact: difference between shocked and baseline GDP gap forecasts
    gdp_impact_predictions = [
        {"date": quarters[-1], "predicted_gdp_change_percent": 0.0, "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_gdp_change_percent": round(fc[0][i] - fc_baseline[0][i], 4), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # Inflation prediction: CPI core-core from shocked forecast
    inflation_predictions = [
        {"date": quarters[-1], "predicted_inflation_percent": round(last_obs[3], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_inflation_percent": round(fc[3][i], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    return {
        "current_gap": {
            "gdp_gap_percent": round(gap_pct, 2),
            "gdp_gap_trillion_yen": gap_trillion,
        },
        "required_fiscal_spending": {
            "amount_trillion_yen": round(required_spending, 1),
            "multiplier": FISCAL_MULTIPLIER,
            "note": _build_spending_note(required_spending),
            "gap_fill_percent": 100.0,
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "gdp_impact": gdp_impact_predictions,
            "inflation_prediction": inflation_predictions,
            "model": "AR(1)",
            "engine": "ar1",
            "assumptions": {
                "lag_order": 1,
                "n_obs": T,
                "n_steps": VAR_PREDICTION_STEPS,
                "variables": VARIABLE_NAMES_STATIC,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
                "multiplier_decay_rate": None,
            },
        },
    }


# ---------------------------------------------------------------------------
# Bayesian VAR (Minnesota prior) — pure-Python 版
# ---------------------------------------------------------------------------

BVAR_DEFAULT_LAMBDA_STATIC = 0.2


def _fit_bvar1_static(Y, lambda_=BVAR_DEFAULT_LAMBDA_STATIC):
    """Bayesian VAR(1) with Minnesota prior. Pure Python 版。

    Returns (c (k,), A (k,k)).
    """
    T = len(Y)
    k = len(Y[0])
    if T < 3:
        return [0.0] * k, _eye(k, 0.0)

    # 各変数の残差標準偏差（単変量 AR(1) の残差で近似）
    sigma = [1.0] * k
    for j in range(k):
        col = [Y[t][j] for t in range(T)]
        c_ar, phi_ar = _fit_ar1_static(col)
        resid = [col[t] - c_ar - phi_ar * col[t - 1] for t in range(1, T)]
        if len(resid) > 1:
            mean_r = sum(resid) / len(resid)
            var_r = sum((r - mean_r) ** 2 for r in resid) / (len(resid) - 1)
            s = var_r ** 0.5
            sigma[j] = max(s, 1e-8)

    # X[(T-1) x (k+1)] = [1, Y_{t-1}], target Yt[t] = Y_{t}
    X = [[1.0] + list(Y[t - 1]) for t in range(1, T)]
    Yt = [list(Y[t]) for t in range(1, T)]
    n_params = k + 1

    # Prior precision (diagonal) と prior mean
    prior_prec = [0.0] * n_params  # index 0 = 定数項 (uninformative)
    prior_mean = [[0.0] * k for _ in range(n_params)]

    for var_idx in range(k):
        row = 1 + var_idx
        # 自変数 lag-1: prior mean = 1, precision = lambda^2
        prior_mean[row][var_idx] = 1.0
        prior_prec[row] = lambda_ ** 2

    # Lambda 対角行列
    Lambda = [[prior_prec[i] if i == j else 0.0 for j in range(n_params)] for i in range(n_params)]

    # X'X + Lambda
    Xt = _transpose(X)
    XtX = _matmul(Xt, X)
    for i in range(n_params):
        XtX[i][i] += prior_prec[i] + 1e-8

    # X'Y + Lambda @ prior_mean
    XtY = _matmul(Xt, Yt)
    Lambda_mu = _matmul(Lambda, prior_mean)
    rhs = [[XtY[i][j] + Lambda_mu[i][j] for j in range(k)] for i in range(n_params)]

    B = _solve_matrix(XtX, rhs)  # (k+1, k)
    c = list(B[0])
    A = [[B[1 + i][j] for i in range(k)] for j in range(k)]

    # 安定化（VAR と同じ行ノルムベース縮小）
    row_norm = max(sum(abs(v) for v in row) for row in A)
    if row_norm > 0.85:
        s = 0.85 / row_norm
        for i in range(k):
            for j in range(k):
                A[i][j] *= s
        mean_y = [sum(row[j] for row in Y) / T for j in range(k)]
        I_minus_As = [[(1.0 if i == j else 0.0) - A[i][j] for j in range(k)] for i in range(k)]
        c = _matvec(I_minus_As, mean_y)
    return c, A


def generate_prediction_bvar(method="maximum"):
    """Bayesian VAR(1) with Minnesota prior の静的JSON生成。"""
    quarters, Y = _build_panel_static(method)
    if not Y:
        return generate_prediction(method)
    T = len(Y)
    c, A = _fit_bvar1_static(Y)

    last_obs = Y[-1]
    gap_pct = last_obs[0]
    gap_trillion = round(gap_pct / 100.0 * VAR_NOMINAL_GDP, 1)
    required_spending = -gap_trillion / FISCAL_MULTIPLIER

    shock_gap_pct = required_spending / VAR_NOMINAL_GDP * 100.0 * FISCAL_MULTIPLIER
    shock_vec = [shock_gap_pct, 0.0, 0.0, 0.0]

    base_fc = _forecast_var1(last_obs, c, A, VAR_PREDICTION_STEPS)
    shock_resp = _irf_var1(A, VAR_PREDICTION_STEPS - 1, shock_vec)
    fc = [
        [base_fc[i][j] + shock_resp[i][j] for j in range(4)]
        for i in range(VAR_PREDICTION_STEPS)
    ]

    future_q = _build_future_quarters(quarters[-1], VAR_PREDICTION_STEPS)
    interest_predictions = [
        {"date": quarters[-1], "predicted_jgb_10y": round(last_obs[1], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_jgb_10y": round(fc[i][1], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    exchange_predictions = [
        {"date": quarters[-1], "predicted_usdjpy": round(last_obs[2], 1), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_usdjpy": round(fc[i][2], 1), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    gdp_impact_predictions = [
        {"date": quarters[-1], "predicted_gdp_change_percent": 0.0, "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_gdp_change_percent": round(fc[i][0] - base_fc[i][0], 4), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    inflation_predictions = [
        {"date": quarters[-1], "predicted_inflation_percent": round(last_obs[3], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_inflation_percent": round(fc[i][3], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    # IRF
    unit_shock = [1.0 / VAR_NOMINAL_GDP * 100.0, 0.0, 0.0, 0.0]
    irf = _irf_var1(A, VAR_PREDICTION_STEPS, unit_shock)
    irf_points = [
        {
            "horizon": h,
            "gdp_gap": round(irf[h][0], 4),
            "jgb_10y": round(irf[h][1], 4),
            "usdjpy": round(irf[h][2], 3),
            "cpi_core_core": round(irf[h][3], 4),
        }
        for h in range(VAR_PREDICTION_STEPS + 1)
    ]

    return {
        "current_gap": {
            "gdp_gap_percent": round(gap_pct, 2),
            "gdp_gap_trillion_yen": gap_trillion,
        },
        "required_fiscal_spending": {
            "amount_trillion_yen": round(required_spending, 1),
            "multiplier": FISCAL_MULTIPLIER,
            "note": _build_spending_note(required_spending),
            "gap_fill_percent": 100.0,
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "gdp_impact": gdp_impact_predictions,
            "inflation_prediction": inflation_predictions,
            "model": "BVAR(1)",
            "engine": "bvar",
            "assumptions": {
                "lag_order": 1,
                "n_obs": T,
                "n_steps": VAR_PREDICTION_STEPS,
                "variables": VARIABLE_NAMES_STATIC,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
                "lambda_tightness": BVAR_DEFAULT_LAMBDA_STATIC,
                "multiplier_decay_rate": None,
            },
            "irf": irf_points,
        },
    }


# ---------------------------------------------------------------------------
# Random Walk with Drift — pure-Python 版
# ---------------------------------------------------------------------------


def _fit_rw_drift_static(y):
    """Random Walk with Drift: mu = 1階差分の平均。"""
    n = len(y)
    if n < 2:
        return 0.0
    diffs = [y[t] - y[t - 1] for t in range(1, n)]
    return sum(diffs) / len(diffs)


def _forecast_rw_static(y0, mu, n_steps):
    out = []
    cur = float(y0)
    for _ in range(n_steps):
        cur = cur + mu
        out.append(cur)
    return out


def generate_prediction_rw(method="maximum"):
    """Random Walk with Drift の静的JSON生成。"""
    quarters, Y = _build_panel_static(method)
    if not Y:
        return generate_prediction(method)
    T = len(Y)
    last_obs = Y[-1]
    gap_pct = last_obs[0]
    gap_trillion = round(gap_pct / 100.0 * VAR_NOMINAL_GDP, 1)
    required_spending = -gap_trillion / FISCAL_MULTIPLIER

    shock_gap_pct = required_spending / VAR_NOMINAL_GDP * 100.0 * FISCAL_MULTIPLIER

    # 各変数のドリフト推定
    drifts = []
    for j in range(4):
        col = [Y[t][j] for t in range(T)]
        drifts.append(_fit_rw_drift_static(col))

    # Baseline forecast (no shock)
    fc_baseline = []
    for j in range(4):
        fc_baseline.append(_forecast_rw_static(last_obs[j], drifts[j], VAR_PREDICTION_STEPS))

    # Shocked forecast: GDPギャップにショック永続注入
    fc = [list(row) for row in zip(*fc_baseline)]  # transpose to (steps, 4)
    for i in range(VAR_PREDICTION_STEPS):
        fc[i][0] += shock_gap_pct  # RW: phi=1 なのでショック永続

    future_q = _build_future_quarters(quarters[-1], VAR_PREDICTION_STEPS)
    interest_predictions = [
        {"date": quarters[-1], "predicted_jgb_10y": round(last_obs[1], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_jgb_10y": round(fc[i][1], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    exchange_predictions = [
        {"date": quarters[-1], "predicted_usdjpy": round(last_obs[2], 1), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_usdjpy": round(fc[i][2], 1), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    gdp_impact_predictions = [
        {"date": quarters[-1], "predicted_gdp_change_percent": 0.0, "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_gdp_change_percent": round(fc[i][0] - fc_baseline[0][i], 4), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]
    # RW: 変数間波及なし → インフレはベースライン
    inflation_predictions = [
        {"date": quarters[-1], "predicted_inflation_percent": round(last_obs[3], 2), "type": "actual"}
    ] + [
        {"date": future_q[i], "predicted_inflation_percent": round(fc_baseline[3][i], 2), "type": "prediction"}
        for i in range(VAR_PREDICTION_STEPS)
    ]

    return {
        "current_gap": {
            "gdp_gap_percent": round(gap_pct, 2),
            "gdp_gap_trillion_yen": gap_trillion,
        },
        "required_fiscal_spending": {
            "amount_trillion_yen": round(required_spending, 1),
            "multiplier": FISCAL_MULTIPLIER,
            "note": _build_spending_note(required_spending),
            "gap_fill_percent": 100.0,
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "gdp_impact": gdp_impact_predictions,
            "inflation_prediction": inflation_predictions,
            "model": "Random Walk",
            "engine": "rw",
            "assumptions": {
                "lag_order": 1,
                "n_obs": T,
                "n_steps": VAR_PREDICTION_STEPS,
                "variables": VARIABLE_NAMES_STATIC,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
                "multiplier_decay_rate": None,
            },
        },
    }


# ---------------------------------------------------------------------------
# Inflation data
# ---------------------------------------------------------------------------
# CPIコアコア（生鮮食品・エネルギー除く= 世界標準 core CPI） / GDPデフレータ /
# 名目賃金（前年同期比%）。
# 実データ差し替え点: 総務省CPI（コアコア）、内閣府GDPデフレータ、厚労省毎月勤労統計。

MOCK_INFLATION = [
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


def generate_inflation():
    today = "2026-04-27"
    return {
        "data": MOCK_INFLATION,
        "source": "総務省CPI（コアコア） / 内閣府GDPデフレータ / 厚労省毎月勤労統計（モック）",
        "boj_target": 2.0,
        "last_updated": today,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 共通レンジ（GDPギャップ実績期間）でデータを揃えるユーティリティ
# ---------------------------------------------------------------------------


def _parse_quarter(label):
    m = re.match(r"^(\d{4})-Q([1-4])$", str(label).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_iso(label):
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", str(label).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _q_index(year, q):
    return year * 4 + (q - 1)


def _date_in_range(date_str, start_yq, end_yq):
    yq = _parse_quarter(date_str)
    if yq is not None:
        return _q_index(*start_yq) <= _q_index(*yq) <= _q_index(*end_yq)
    iso = _parse_iso(date_str)
    if iso is not None:
        year, month = iso
        q = (month - 1) // 3 + 1
        return _q_index(*start_yq) <= _q_index(year, q) <= _q_index(*end_yq)
    return True


def _filter_to_range(items, start_yq, end_yq, key="date", label=None):
    out = [it for it in items if _date_in_range(it.get(key, ""), start_yq, end_yq)]
    if items and len(out) < max(2, len(items) // 4) and label:
        print(
            f"WARN: 共通レンジ適用で {label} が {len(items)} → {len(out)} に減少"
        )
    return out


def _gdp_gap_range(gdp_gap_data):
    """gdp_gap_data の estimated_average から (start_yq, end_yq) を抽出。"""
    series = gdp_gap_data["estimated_average"]["data"]
    if not series:
        return (2022, 1), (2024, 4)
    start = _parse_quarter(series[0]["date"]) or (2022, 1)
    end = _parse_quarter(series[-1]["date"]) or (2024, 4)
    return start, end


def _apply_unified_range(gdp_gap, fund_demand, rates, inflation):
    """gdp_gap の実績期間に他3データを揃える（in-place 編集）。"""
    start_yq, end_yq = _gdp_gap_range(gdp_gap)

    # gdp-gap 自体（cabinet_office, civilian, maximum も念のため）
    for key in ("cabinet_office", "estimated_average", "estimated_maximum",
                "estimated_civilian", "estimated"):
        if key in gdp_gap and "data" in gdp_gap[key]:
            gdp_gap[key]["data"] = _filter_to_range(
                gdp_gap[key]["data"], start_yq, end_yq, label=f"gdp_gap.{key}"
            )

    # fund-demand
    fund_demand["flow_of_funds"]["data"] = _filter_to_range(
        fund_demand["flow_of_funds"]["data"], start_yq, end_yq, label="flow_of_funds"
    )
    fund_demand["bank_lending"]["data"] = _filter_to_range(
        fund_demand["bank_lending"]["data"], start_yq, end_yq, label="bank_lending"
    )

    # rates
    rates["interest_rates"]["fred"] = _filter_to_range(
        rates["interest_rates"]["fred"], start_yq, end_yq, label="rates.fred"
    )
    rates["interest_rates"]["boj"] = _filter_to_range(
        rates["interest_rates"]["boj"], start_yq, end_yq, label="rates.boj"
    )
    rates["exchange_rates"]["fred"] = _filter_to_range(
        rates["exchange_rates"]["fred"], start_yq, end_yq, label="fx.fred"
    )

    # inflation
    inflation["data"] = _filter_to_range(
        inflation["data"], start_yq, end_yq, label="inflation"
    )


def main():
    prediction_max = generate_prediction("maximum")
    gdp_gap = generate_gdp_gap()
    fund_demand = generate_fund_demand()
    rates = generate_rates()
    inflation = generate_inflation()

    # 共通レンジ統一: GDPギャップの実績期間に各実績データを揃える
    # 予測（prediction-*.json）は据え置き
    _apply_unified_range(gdp_gap, fund_demand, rates, inflation)

    files = {
        "gdp-gap.json": gdp_gap,
        "fund-demand.json": fund_demand,
        "rates.json": rates,
        # デフォルト = maximum（後方互換のため prediction.json も残す）
        "prediction.json": prediction_max,
        "prediction-maximum.json": prediction_max,
        "prediction-average.json": generate_prediction("average"),
        "prediction-cabinet_office.json": generate_prediction("cabinet_office"),
        "prediction-civilian.json": generate_prediction("civilian"),
        "inflation.json": inflation,
    }
    # 統計モデル（VAR / BVAR / AR(1) / RW）の事前計算 JSON
    for m in ("maximum", "average", "cabinet_office", "civilian"):
        files[f"prediction-{m}-var.json"] = generate_prediction_var(m)
        files[f"prediction-{m}-bvar.json"] = generate_prediction_bvar(m)
        files[f"prediction-{m}-ar1.json"] = generate_prediction_ar1(m)
        files[f"prediction-{m}-rw.json"] = generate_prediction_rw(m)
        # IS-LM も engine 明示版を追加（フロントの統一読み込みに対応）
        files[f"prediction-{m}-is_lm.json"] = generate_prediction(m)

    for output_dir in OUTPUT_DIRS:
        os.makedirs(output_dir, exist_ok=True)
        for filename, data in files.items():
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Generated: {filepath}")


if __name__ == "__main__":
    main()
