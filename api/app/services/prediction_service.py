"""IS-LM model based prediction service.

Model overview:
  1. Compute current GDP gap from gdp_gap_service
  2. Required fiscal spending = gap / fiscal_multiplier
  3. IS curve: Y = C(Y-T) + I(r) + G  →  fiscal expansion shifts IS right
  4. LM curve: M/P = L(Y, r)           →  higher Y raises money demand → r rises
  5. Interest rate differential → exchange rate via UIP (uncovered interest parity)

All parameters are defined as constants for easy future adjustment.
"""

from __future__ import annotations

import logging

from app.models.schemas import (
    Assumptions,
    CurrentGap,
    ExchangeRatePrediction,
    ImpactPrediction,
    InterestRatePrediction,
    PredictionResponse,
    RequiredFiscalSpending,
)
from app.services.gdp_gap_service import get_gdp_gap

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IS-LM Model Parameters (constants, tunable)
# ---------------------------------------------------------------------------

# Fiscal multiplier: dY/dG
FISCAL_MULTIPLIER = 1.0

# Money demand elasticity w.r.t. income (LM slope parameter)
MONEY_DEMAND_ELASTICITY = 0.5

# Investment sensitivity to interest rate (IS slope parameter)
INVESTMENT_SENSITIVITY = 0.3

# Nominal GDP (trillion yen, approximate)
NOMINAL_GDP = 560.0

# Current baseline interest rates
BASELINE_JGB_10Y = 0.85  # percent
BASELINE_USDJPY = 150.0

# UIP sensitivity: how much JPY appreciates per 1pp rise in JGB yield
# (simplified: higher domestic rates → stronger yen)
UIP_SENSITIVITY = 2.0  # yen per percentage point

# Quarters for prediction (3 years = 12 quarters)
PREDICTION_QUARTERS = [
    f"{y}-Q{q}" for y in range(2025, 2028) for q in range(1, 5)
]


# ---------------------------------------------------------------------------
# IS-LM calculation
# ---------------------------------------------------------------------------


def _compute_is_lm_impact(
    fiscal_spending_trillion: float,
) -> tuple[list[float], list[float]]:
    """Compute predicted interest rates and exchange rates per quarter.

    Simplified IS-LM:
      - Fiscal expansion dG shifts IS right → both Y and r increase
      - dr = (dG * FISCAL_MULTIPLIER * MONEY_DEMAND_ELASTICITY)
             / (INVESTMENT_SENSITIVITY + MONEY_DEMAND_ELASTICITY) / NOMINAL_GDP * 100
      - Spread over 12 quarters with gradual phase-in

    Returns (jgb_10y_list, usdjpy_list) for each quarter.
    """
    n = len(PREDICTION_QUARTERS)

    # Total interest rate impact from fiscal expansion (percentage points)
    total_dr = (
        fiscal_spending_trillion
        * FISCAL_MULTIPLIER
        * MONEY_DEMAND_ELASTICITY
        / (INVESTMENT_SENSITIVITY + MONEY_DEMAND_ELASTICITY)
        / NOMINAL_GDP
        * 100
    )

    # Phase in: 0% at Q1 (actual), then ramp to 100% by Q5, hold steady after
    ramp_quarters = 4
    phase_in = [0.0] + [
        min(1.0, i / ramp_quarters) for i in range(1, n)
    ]

    jgb_rates: list[float] = []
    usdjpy_rates: list[float] = []

    for frac in phase_in:
        dr = total_dr * frac
        r = round(BASELINE_JGB_10Y + dr, 2)
        # UIP: higher domestic rate → yen appreciation (lower USD/JPY)
        fx = round(BASELINE_USDJPY - dr * UIP_SENSITIVITY, 1)
        jgb_rates.append(r)
        usdjpy_rates.append(fx)

    return jgb_rates, usdjpy_rates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_prediction() -> PredictionResponse:
    """Run IS-LM prediction based on current GDP gap."""

    # Get latest GDP gap estimate
    try:
        gdp_gap_data = await get_gdp_gap()
        latest = gdp_gap_data.estimated.data[-1]
        gap_pct = latest.gdp_gap_percent
        gap_trillion = round(gap_pct / 100.0 * NOMINAL_GDP, 1)
    except Exception:
        logger.exception("Failed to get GDP gap for prediction, using defaults")
        gap_pct = -2.5
        gap_trillion = -14.0

    # Required fiscal spending to close the gap
    required_spending = abs(gap_trillion) / FISCAL_MULTIPLIER

    # IS-LM impact
    jgb_rates, usdjpy_rates = _compute_is_lm_impact(required_spending)

    # Build prediction arrays
    interest_predictions = [
        InterestRatePrediction(
            date=q,
            predicted_jgb_10y=r,
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, r) in enumerate(zip(PREDICTION_QUARTERS, jgb_rates))
    ]

    exchange_predictions = [
        ExchangeRatePrediction(
            date=q,
            predicted_usdjpy=fx,
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, fx) in enumerate(zip(PREDICTION_QUARTERS, usdjpy_rates))
    ]

    return PredictionResponse(
        current_gap=CurrentGap(
            gdp_gap_percent=gap_pct,
            gdp_gap_trillion_yen=gap_trillion,
        ),
        required_fiscal_spending=RequiredFiscalSpending(
            amount_trillion_yen=round(required_spending, 1),
            multiplier=FISCAL_MULTIPLIER,
        ),
        impact_prediction=ImpactPrediction(
            interest_rate=interest_predictions,
            exchange_rate=exchange_predictions,
            assumptions=Assumptions(
                money_demand_elasticity=MONEY_DEMAND_ELASTICITY,
                investment_sensitivity=INVESTMENT_SENSITIVITY,
                fiscal_multiplier=FISCAL_MULTIPLIER,
            ),
        ),
    )
