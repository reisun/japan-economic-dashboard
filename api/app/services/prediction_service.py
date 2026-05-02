"""IS-LM model based prediction service.

Model overview:
  1. Compute current GDP gap from gdp_gap_service
  2. Required fiscal spending = gap / fiscal_multiplier
  3. IS curve: Y = C(Y-T) + I(r) + G  →  fiscal expansion shifts IS right
  4. LM curve: M/P = L(Y, r)           →  higher Y raises money demand → r rises
  5. Interest rate differential → exchange rate via UIP (uncovered interest parity)

All parameters are defined as constants for easy future adjustment.
Nominal GDP is fetched dynamically from FRED (JPNNGDP) with a static fallback.
"""

from __future__ import annotations

import logging

from app.models.schemas import (
    Assumptions,
    CurrentGap,
    ExchangeRatePrediction,
    GdpGapResponse,
    GdpImpactPoint,
    ImpactPrediction,
    InflationPredictionPoint,
    InterestRatePrediction,
    PredictionResponse,
    RequiredFiscalSpending,
)
from app.services.gdp_gap_service import get_gdp_gap
from app.services.prediction_common import (
    BASELINE_JGB_10Y,
    BASELINE_USDJPY,
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
# IS-LM Model Parameters (constants, tunable)
# ---------------------------------------------------------------------------

# Money demand elasticity w.r.t. income (LM slope parameter)
MONEY_DEMAND_ELASTICITY = 0.5

# Investment sensitivity to interest rate (IS slope parameter)
INVESTMENT_SENSITIVITY = 0.3

# Zero Lower Bound for JGB 10Y nominal rate (percent)
ZLB_RATE = 0.0


# ---------------------------------------------------------------------------
# IS-LM calculation (quarterly spending with multiplier decay)
# ---------------------------------------------------------------------------


def _compute_is_lm_impact(
    quarterly_spending: float,
    n_quarters: int,
    nominal_gdp: float,
    baseline_jgb: float = BASELINE_JGB_10Y,
    baseline_fx: float = BASELINE_USDJPY,
    uip_sensitivity: float = UIP_SENSITIVITY,
) -> tuple[list[float], list[float], list[float], bool]:
    """Compute predicted rates and GDP impacts per quarter with decay.

    Spending is injected each quarter starting at Q1. Each injection's GDP
    impact decays at MULTIPLIER_DECAY_RATE per quarter, creating a realistic
    hump-shaped response.

    Returns (jgb_10y_list, usdjpy_list, gdp_impacts_pct, zlb_binding).
    Q0 is "actual" (zero impact), Q1..Q(n-1) are predictions.
    """
    # Compute cumulative GDP impact path with decay
    cumulative_impacts: list[float] = [0.0]  # Q0: actual baseline
    for t in range(1, n_quarters):
        # Sum of decayed impacts from all spending injections up to quarter t
        impact = sum(
            quarterly_spending * FISCAL_MULTIPLIER
            * (MULTIPLIER_DECAY_RATE ** (t - 1 - s))
            / nominal_gdp * 100
            for s in range(t)  # spending injected at quarters 1..t
        )
        cumulative_impacts.append(impact)

    jgb_rates: list[float] = []
    usdjpy_rates: list[float] = []
    zlb_binding = False

    for gdp_pct in cumulative_impacts:
        # LM curve: interest rate change from GDP impact
        dr = (
            gdp_pct / 100 * nominal_gdp  # back to trillion yen impact
            * MONEY_DEMAND_ELASTICITY
            / (INVESTMENT_SENSITIVITY + MONEY_DEMAND_ELASTICITY)
            / nominal_gdp
            * 100
        )
        r = baseline_jgb + dr

        # Zero Lower Bound constraint
        if r < ZLB_RATE:
            r = ZLB_RATE
            zlb_binding = True
            effective_dr = ZLB_RATE - baseline_jgb
        else:
            effective_dr = dr

        r = round(r, 2)
        # UIP: higher domestic rate -> yen appreciation (lower USD/JPY)
        fx = round(baseline_fx - effective_dr * uip_sensitivity, 1)
        jgb_rates.append(r)
        usdjpy_rates.append(fx)

    return jgb_rates, usdjpy_rates, cumulative_impacts, zlb_binding


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_prediction(
    method: str = "maximum",
    gap_fill_percent: float | None = None,
    engine: str = "is_lm",
    uip_sensitivity: float | None = None,
) -> PredictionResponse:
    """予測モデル切替対応のディスパッチャ。

    engine = "is_lm" (デフォルト, 構造モデル) / "var" / "ar1" を選択可能。
    gap_fill_percent: GDPギャップの何%を埋める財政政策か (0-150%, デフォルト100%)
    """
    if engine == "var":
        from app.services.var_service import get_var_prediction

        return await get_var_prediction(
            method=method, gap_fill_percent=gap_fill_percent
        )
    if engine == "bvar":
        from app.services.var_service import get_bvar_prediction

        return await get_bvar_prediction(
            method=method, gap_fill_percent=gap_fill_percent
        )
    if engine == "ar1":
        from app.services.var_service import get_ar1_prediction

        return await get_ar1_prediction(
            method=method, gap_fill_percent=gap_fill_percent
        )
    if engine == "rw":
        from app.services.var_service import get_rw_prediction

        return await get_rw_prediction(
            method=method, gap_fill_percent=gap_fill_percent
        )
    if engine == "mvpy":
        from app.services.mvpy_service import get_mvpy_prediction

        return await get_mvpy_prediction(
            method=method,
            gap_fill_percent=gap_fill_percent,
            uip_sensitivity=uip_sensitivity,
        )
    if engine == "nkpc":
        from app.services.nkpc_service import get_nkpc_prediction

        return await get_nkpc_prediction(
            method=method,
            gap_fill_percent=gap_fill_percent,
            uip_sensitivity=uip_sensitivity,
        )

    # IS-LM (デフォルト)
    if method not in VALID_METHODS:
        method = "maximum"

    # Resolve gap fill percent
    effective_gap_fill = gap_fill_percent if gap_fill_percent is not None else DEFAULT_GAP_FILL_PERCENT

    # Fetch dynamic nominal GDP
    nominal_gdp = _get_nominal_gdp()

    # Fetch dynamic baseline rates
    baseline_jgb, baseline_fx = _get_latest_rates()

    # Get latest GDP gap estimate
    gdp_gap_data: GdpGapResponse | None = None
    try:
        gdp_gap_data = await get_gdp_gap()
        if method == "cabinet_office":
            latest_co = gdp_gap_data.cabinet_office.data[-1]
            gap_pct = latest_co.gdp_gap_percent
        elif method == "average":
            gap_pct = gdp_gap_data.estimated_average.data[-1].gdp_gap_percent
        elif method == "civilian":
            gap_pct = gdp_gap_data.estimated_civilian.data[-1].gdp_gap_percent
        else:  # maximum
            gap_pct = gdp_gap_data.estimated_maximum.data[-1].gdp_gap_percent
        gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)
    except Exception:
        logger.exception("Failed to get GDP gap for prediction, using defaults")
        gap_pct = -2.5
        gap_trillion = -14.0

    # Compute annual spending from gap fill percentage
    # gap_trillion < 0 (deflation gap) -> annual_spending > 0 (expansionary)
    annual_spending = -gap_trillion / FISCAL_MULTIPLIER * effective_gap_fill / 100
    quarterly_spending = annual_spending / 4

    # Resolve effective UIP sensitivity
    effective_uip = uip_sensitivity if uip_sensitivity is not None else UIP_SENSITIVITY

    # IS-LM impact with quarterly spending and decay
    quarters = _build_prediction_quarters()
    jgb_rates, usdjpy_rates, gdp_impacts_pct, zlb_binding = _compute_is_lm_impact(
        quarterly_spending,
        len(quarters),
        nominal_gdp,
        baseline_jgb=baseline_jgb,
        baseline_fx=baseline_fx,
        uip_sensitivity=effective_uip,
    )

    # Build prediction arrays
    interest_predictions = [
        InterestRatePrediction(
            date=q,
            predicted_jgb_10y=r,
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, r) in enumerate(zip(quarters, jgb_rates))
    ]

    exchange_predictions = [
        ExchangeRatePrediction(
            date=q,
            predicted_usdjpy=fx,
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, fx) in enumerate(zip(quarters, usdjpy_rates))
    ]

    # GDP impact predictions from the decay model
    gdp_impact_predictions = [
        GdpImpactPoint(
            date=q,
            predicted_gdp_change_percent=round(impact, 4),
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, impact) in enumerate(zip(quarters, gdp_impacts_pct))
    ]

    # Estimate Phillips curve slope from data (method-specific)
    pc_slope, pc_r2, pc_n, pc_se = _estimate_phillips_slope(method, gdp_gap_data)

    # Phillips curve inflation prediction: fiscal policy change drives inflation change.
    # Current inflation already reflects current gap, so only the fiscal impact matters.
    baseline_inflation = _get_baseline_inflation()
    inflation_predictions = [
        InflationPredictionPoint(
            date=q,
            predicted_inflation_percent=round(
                baseline_inflation + pc_slope * impact,
                2,
            ),
            type="actual" if i == 0 else "prediction",
        )
        for i, (q, impact) in enumerate(zip(quarters, gdp_impacts_pct))
    ]

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
            model="IS-LM",
            engine="is_lm",
            assumptions=Assumptions(
                money_demand_elasticity=MONEY_DEMAND_ELASTICITY,
                investment_sensitivity=INVESTMENT_SENSITIVITY,
                fiscal_multiplier=FISCAL_MULTIPLIER,
                nominal_gdp_trillion_yen=nominal_gdp,
                uip_sensitivity=effective_uip,
                baseline_jgb_10y=baseline_jgb,
                baseline_usdjpy=baseline_fx,
                zlb_binding=zlb_binding,
                multiplier_decay_rate=MULTIPLIER_DECAY_RATE,
                phillips_curve_slope=pc_slope,
                phillips_r_squared=pc_r2,
                phillips_n_obs=pc_n,
                phillips_std_error=pc_se,
                baseline_inflation=baseline_inflation,
            ),
        ),
    )
