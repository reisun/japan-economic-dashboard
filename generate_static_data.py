#!/usr/bin/env python3
"""Generate static JSON data files for GitHub Pages deployment.

Reproduces the backend mock data and HP filter calculations
without requiring numpy/scipy/pydantic.
"""

import json
import os
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "web", "public", "api", "v1")

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


def generate_gdp_gap():
    today = "2026-04-27"

    potential = hp_filter(MOCK_REAL_GDP, 1600.0)

    estimated_data = []
    for i, q in enumerate(QUARTERS):
        gap_pct = round((MOCK_REAL_GDP[i] - potential[i]) / potential[i] * 100, 2)
        estimated_data.append({
            "date": q,
            "real_gdp": round(MOCK_REAL_GDP[i], 1),
            "potential_gdp": round(potential[i], 1),
            "gdp_gap_percent": gap_pct,
        })

    return {
        "cabinet_office": {
            "data": MOCK_CABINET_DATA,
            "source": "内閣府",
            "last_updated": today,
        },
        "estimated": {
            "data": estimated_data,
            "method": "HP Filter",
            "last_updated": today,
        },
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


def generate_prediction():
    # Get GDP gap from estimated data
    gdp_gap_data = generate_gdp_gap()
    latest_estimated = gdp_gap_data["estimated"]["data"][-1]
    gap_pct = latest_estimated["gdp_gap_percent"]
    gap_trillion = round(gap_pct / 100.0 * NOMINAL_GDP, 1)

    # Required fiscal spending
    required_spending = abs(gap_trillion) / FISCAL_MULTIPLIER

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
            "note": "デフレギャップ解消に必要な財政支出",
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = {
        "gdp-gap.json": generate_gdp_gap(),
        "fund-demand.json": generate_fund_demand(),
        "rates.json": generate_rates(),
        "prediction.json": generate_prediction(),
    }

    for filename, data in files.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Generated: {filepath}")


if __name__ == "__main__":
    main()
