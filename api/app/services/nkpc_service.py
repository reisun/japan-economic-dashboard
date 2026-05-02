"""New Keynesian Phillips Curve (NKPC) prediction service.

Model overview:
  pi_t = beta * E[pi_{t+1}] + kappa * gap_t

  beta:  Discount factor (~0.99)
  kappa: Output gap sensitivity (estimated from Phillips curve OLS)
  E[pi]: Hybrid inflation expectation (adaptive + forward-looking)

Expectation formation (hybrid):
  adaptive  = decay-weighted past inflation
  forward   = inflation_target + fiscal_impact_expected
  E[pi]     = omega * forward + (1 - omega) * adaptive

Interest rate: Taylor rule
  i = r* + pi + 0.5*(pi - pi*) + 0.5*gap
  r* = natural real rate (~0.5%)

Exchange rate: UIP (same as IS-LM)
"""

from __future__ import annotations

import logging

from app.models.schemas import (
    Assumptions,
    CurrentGap,
    ExchangeRatePrediction,
    GdpImpactPoint,
    ImpactPrediction,
    InflationPredictionPoint,
    InterestRatePrediction,
    PredictionResponse,
    RequiredFiscalSpending,
)
from app.services.gdp_gap_service import get_gdp_gap
from app.services.prediction_common import (
    DEFAULT_GAP_FILL_PERCENT,
    FISCAL_MULTIPLIER,
    MULTIPLIER_DECAY_RATE,
    UIP_SENSITIVITY,
    VALID_METHODS,
    _build_prediction_quarters,
    _build_spending_note,
    _estimate_phillips_slope,
    _get_baseline_inflation,
    _get_latest_rates,
    _get_nominal_gdp,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NKPC Model Parameters
# ---------------------------------------------------------------------------

# Discount factor (quarterly)
BETA = 0.99

# Forward-looking weight in hybrid expectation (0=pure adaptive, 1=pure forward)
OMEGA = 0.5

# BOJ inflation target (%)
INFLATION_TARGET = 2.0

# Adaptive expectation decay weight
ADAPTIVE_DECAY = 0.8

# Natural real interest rate for Taylor rule (%)
NATURAL_REAL_RATE = 0.5

# Taylor rule coefficients
TAYLOR_INFLATION_COEFF = 0.5  # response to inflation gap
TAYLOR_OUTPUT_COEFF = 0.5  # response to output gap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_nkpc_prediction(
    method: str = "maximum",
    gap_fill_percent: float | None = None,
    uip_sensitivity: float | None = None,
) -> PredictionResponse:
    """ニューケインジアン・フィリップス曲線 (NKPC) による予測。

    pi_t = beta * E[pi_{t+1}] + kappa * gap_t

    適応的期待と前方視的期待のハイブリッドでインフレを予測し、
    テイラールールで金利、UIPで為替を決定する。

    Parameters
    ----------
    method : GDPギャップ推計手法
    gap_fill_percent : GDPギャップの何%を埋める財政政策か (0-150%)
    uip_sensitivity : UIP感応度（円/pp）
    """
    if method not in VALID_METHODS:
        method = "maximum"

    effective_gap_fill = (
        gap_fill_percent if gap_fill_percent is not None else DEFAULT_GAP_FILL_PERCENT
    )

    # Fetch data
    nominal_gdp = _get_nominal_gdp()
    baseline_jgb, baseline_fx = _get_latest_rates()
    baseline_inflation = _get_baseline_inflation()

    # GDP gap
    gdp_gap_data = None
    try:
        gdp_gap_data = await get_gdp_gap()
        if method == "cabinet_office":
            gap_pct = gdp_gap_data.cabinet_office.data[-1].gdp_gap_percent
        elif method == "average":
            gap_pct = gdp_gap_data.estimated_average.data[-1].gdp_gap_percent
        elif method == "civilian":
            gap_pct = gdp_gap_data.estimated_civilian.data[-1].gdp_gap_percent
        else:
            gap_pct = gdp_gap_data.estimated_maximum.data[-1].gdp_gap_percent
        gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)
    except Exception:
        logger.exception("Failed to get GDP gap for NKPC prediction")
        gap_pct = -2.5
        gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)

    # Phillips curve slope estimation -> use as kappa
    pc_slope, pc_r2, pc_n, pc_se = _estimate_phillips_slope(method, gdp_gap_data)
    kappa = pc_slope

    # Fiscal spending
    annual_spending = -gap_trillion / FISCAL_MULTIPLIER * effective_gap_fill / 100
    quarterly_spending = annual_spending / 4

    # Resolve UIP sensitivity
    effective_uip = uip_sensitivity if uip_sensitivity is not None else UIP_SENSITIVITY

    # Build quarterly predictions
    quarters = _build_prediction_quarters()
    n_quarters = len(quarters)

    interest_predictions: list[InterestRatePrediction] = []
    exchange_predictions: list[ExchangeRatePrediction] = []
    gdp_impact_predictions: list[GdpImpactPoint] = []
    inflation_predictions: list[InflationPredictionPoint] = []

    # Sequential NKPC calculation
    pi_prev = baseline_inflation  # previous quarter's inflation

    for t in range(n_quarters):
        if t == 0:
            # Q0: actual baseline
            interest_predictions.append(
                InterestRatePrediction(
                    date=quarters[0],
                    predicted_jgb_10y=round(baseline_jgb, 2),
                    type="actual",
                )
            )
            exchange_predictions.append(
                ExchangeRatePrediction(
                    date=quarters[0],
                    predicted_usdjpy=round(baseline_fx, 1),
                    type="actual",
                )
            )
            gdp_impact_predictions.append(
                GdpImpactPoint(
                    date=quarters[0],
                    predicted_gdp_change_percent=0.0,
                    type="actual",
                )
            )
            inflation_predictions.append(
                InflationPredictionPoint(
                    date=quarters[0],
                    predicted_inflation_percent=round(baseline_inflation, 2),
                    type="actual",
                )
            )
            continue

        # Cumulative GDP impact with multiplier decay (same as IS-LM)
        gdp_impact = sum(
            quarterly_spending
            * FISCAL_MULTIPLIER
            * (MULTIPLIER_DECAY_RATE ** (t - 1 - s))
            / nominal_gdp
            * 100
            for s in range(t)
        )

        # Current gap including fiscal impact
        gap_t = gap_pct + gdp_impact

        # Hybrid inflation expectation
        # Adaptive component: weighted decay from previous inflation
        adaptive = ADAPTIVE_DECAY * pi_prev + (1.0 - ADAPTIVE_DECAY) * baseline_inflation

        # Forward-looking component: target + expected fiscal effect on inflation
        # The fiscal effect on inflation expectation scales with kappa * gap change
        fiscal_inflation_effect = kappa * gdp_impact
        forward = INFLATION_TARGET + fiscal_inflation_effect

        # Hybrid expectation
        e_pi_next = OMEGA * forward + (1.0 - OMEGA) * adaptive

        # NKPC: pi_t = beta * E[pi_{t+1}] + kappa * gap_t
        pi_t = BETA * e_pi_next + kappa * gap_t

        # Taylor rule: i = r* + pi + 0.5*(pi - pi*) + 0.5*gap
        taylor_rate = (
            NATURAL_REAL_RATE
            + pi_t
            + TAYLOR_INFLATION_COEFF * (pi_t - INFLATION_TARGET)
            + TAYLOR_OUTPUT_COEFF * gap_t
        )
        taylor_rate = max(taylor_rate, 0.0)  # ZLB

        # UIP: exchange rate
        rate_diff = taylor_rate - baseline_jgb
        predicted_fx = baseline_fx - rate_diff * effective_uip

        interest_predictions.append(
            InterestRatePrediction(
                date=quarters[t],
                predicted_jgb_10y=round(taylor_rate, 2),
                type="prediction",
            )
        )
        exchange_predictions.append(
            ExchangeRatePrediction(
                date=quarters[t],
                predicted_usdjpy=round(predicted_fx, 1),
                type="prediction",
            )
        )
        gdp_impact_predictions.append(
            GdpImpactPoint(
                date=quarters[t],
                predicted_gdp_change_percent=round(gdp_impact, 4),
                type="prediction",
            )
        )
        inflation_predictions.append(
            InflationPredictionPoint(
                date=quarters[t],
                predicted_inflation_percent=round(pi_t, 2),
                type="prediction",
            )
        )

        # Update previous inflation for next iteration
        pi_prev = pi_t

    return PredictionResponse(
        current_gap=CurrentGap(
            gdp_gap_percent=gap_pct,
            gdp_gap_trillion_yen=gap_trillion,
        ),
        required_fiscal_spending=RequiredFiscalSpending(
            amount_trillion_yen=round(annual_spending, 1),
            multiplier=FISCAL_MULTIPLIER,
            note=_build_spending_note(annual_spending, effective_gap_fill),
            gap_fill_percent=effective_gap_fill,
        ),
        impact_prediction=ImpactPrediction(
            interest_rate=interest_predictions,
            exchange_rate=exchange_predictions,
            gdp_impact=gdp_impact_predictions,
            inflation_prediction=inflation_predictions,
            model="NKPC",
            engine="nkpc",
            assumptions=Assumptions(
                fiscal_multiplier=FISCAL_MULTIPLIER,
                nominal_gdp_trillion_yen=nominal_gdp,
                baseline_jgb_10y=baseline_jgb,
                baseline_usdjpy=baseline_fx,
                baseline_inflation=baseline_inflation,
                multiplier_decay_rate=MULTIPLIER_DECAY_RATE,
                phillips_curve_slope=pc_slope,
                phillips_r_squared=pc_r2,
                phillips_n_obs=pc_n,
                phillips_std_error=pc_se,
                discount_factor=BETA,
                kappa=round(kappa, 4),
                forward_weight=OMEGA,
                inflation_target=INFLATION_TARGET,
            ),
        ),
    )
