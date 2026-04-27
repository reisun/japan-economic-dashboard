#!/usr/bin/env python3
"""Generate static JSON data files for GitHub Pages deployment.

Reproduces the backend mock data and HP filter calculations
without requiring numpy/scipy/pydantic.
"""

import json
import os
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
# 最大概念潜在GDP: Cobb-Douglas 生産関数アプローチ（生産関数による直接推計）
# ---------------------------------------------------------------------------
# Y_potential_t = A_trend_t * (L_full_t)^(1-α) * (K_t)^α
#   α=0.33（資本分配率, 日本標準）
#   NAIRU=2.5%（構造的失業率）
#   A_t = Y_t / (L_t^(1-α) * K_t^α) を実績から逆算 → HP平滑化
#   L_full = 労働力人口 × 平均労働時間 × (1-NAIRU)
# 実データ差し替え点:
#   - 労働力人口/労働時間/失業率: 総務省統計局・厚労省毎月勤労統計
#   - 民間資本ストック: 内閣府SNA系列
# ---------------------------------------------------------------------------

_CD_ALPHA = 0.33
_NAIRU = 0.025

MOCK_LABOR_FORCE = [
    69.0, 69.0, 68.9, 68.8,
    68.8, 68.7, 68.6, 68.5,
    68.5, 68.4, 68.3, 68.2,
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
    """最大概念: Cobb-Douglas 生産関数アプローチ。
    完全雇用ベースの労働投入と実績資本ストックを用いて潜在GDPを直接推計。
    実績失業率 ≥ NAIRU である限り構造的に gap ≤ 0 となる。"""
    n = len(real_gdp)

    def resize(seq):
        if len(seq) == n:
            return list(seq)
        if len(seq) > n:
            return list(seq[-n:])
        return [seq[0]] * (n - len(seq)) + list(seq)

    labor = resize(MOCK_LABOR_FORCE)
    hours = resize(MOCK_HOURS)
    unemp = [u / 100.0 for u in resize(MOCK_UNEMPLOYMENT)]
    capital = resize(MOCK_CAPITAL_STOCK)

    L_actual = [labor[i] * hours[i] * (1.0 - unemp[i]) for i in range(n)]
    L_full = [labor[i] * hours[i] * (1.0 - _NAIRU) for i in range(n)]

    A_implied = [
        real_gdp[i] / ((L_actual[i] ** (1.0 - _CD_ALPHA)) * (capital[i] ** _CD_ALPHA))
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
        pot = A_max[i] * (L_full[i] ** (1.0 - _CD_ALPHA)) * (capital[i] ** _CD_ALPHA)
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


def generate_gdp_gap():
    today = "2026-04-27"

    average_data = _estimate_average(MOCK_REAL_GDP, QUARTERS)
    maximum_data = _estimate_maximum(MOCK_REAL_GDP, QUARTERS)

    average_block = {
        "data": average_data,
        "method": "HP Filter (平均概念)",
        "last_updated": today,
    }
    maximum_block = {
        "data": maximum_data,
        "method": "Cobb-Douglas 生産関数 (TFPトレンド × 完全雇用労働投入 × 資本ストック, α=0.33, NAIRU=2.5%)",
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
        # 後方互換エイリアス
        "estimated": average_block,
    }


# ---------------------------------------------------------------------------
# Fund Demand data
# ---------------------------------------------------------------------------

def generate_fund_demand():
    quarters = [
        "2022-Q1", "2022-Q2", "2022-Q3", "2022-Q4",
        "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
        "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4",
    ]

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

    yahoo_fx = [
        {"date": d, "usdjpy": round(148.0 + i * 0.5, 1)} for i, d in enumerate(dates)
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
            "yahoo_finance": yahoo_fx,
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
PREDICTION_QUARTERS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]


def generate_prediction(method="maximum"):
    # Get GDP gap based on method
    gdp_gap_data = generate_gdp_gap()
    if method == "cabinet_office":
        gap_pct = gdp_gap_data["cabinet_office"]["data"][-1]["gdp_gap_percent"]
    elif method == "average":
        gap_pct = gdp_gap_data["estimated_average"]["data"][-1]["gdp_gap_percent"]
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

    interest_predictions = []
    exchange_predictions = []

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
        },
        "impact_prediction": {
            "interest_rate": interest_predictions,
            "exchange_rate": exchange_predictions,
            "model": "IS-LM",
            "assumptions": {
                "money_demand_elasticity": MONEY_DEMAND_ELASTICITY,
                "investment_sensitivity": INVESTMENT_SENSITIVITY,
                "fiscal_multiplier": FISCAL_MULTIPLIER,
            },
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prediction_max = generate_prediction("maximum")
    files = {
        "gdp-gap.json": generate_gdp_gap(),
        "fund-demand.json": generate_fund_demand(),
        "rates.json": generate_rates(),
        # デフォルト = maximum（後方互換のため prediction.json も残す）
        "prediction.json": prediction_max,
        "prediction-maximum.json": prediction_max,
        "prediction-average.json": generate_prediction("average"),
        "prediction-cabinet_office.json": generate_prediction("cabinet_office"),
    }

    for output_dir in OUTPUT_DIRS:
        os.makedirs(output_dir, exist_ok=True)
        for filename, data in files.items():
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Generated: {filepath}")


if __name__ == "__main__":
    main()
