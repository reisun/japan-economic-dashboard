"""MV=PY (Quantity Theory of Money) prediction service.

Model overview:
  M x V = P x Y  (Fisher equation of exchange)

  M: Money supply (M3) -- fetched from FRED or fallback
  V: Velocity of money -- derived from nominal GDP / M, adjusted by gap fill
  P: Price level (GDP deflator or CPI proxy)
  Y: Real GDP

Key mechanism:
  Fiscal policy that fills the GDP gap raises aggregate demand, which
  increases the velocity of money (V). The change in V is proportional
  to the gap fill percentage and the size of the gap itself.

  V_new = V_base * (1 + V_change_rate * fiscal_impact_fraction)

  The resulting increase in nominal GDP (M * V_new) splits into
  real output growth and inflation via the GDP deflator.

Interest rate: Fisher equation  i = r_real + pi_expected
Exchange rate: PPP-based  -- JPY depreciation proportional to
               Japan-US inflation differential
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
from app.services.cache import cached
from app.services.data_utils import fetch_fred_series
from app.services.gdp_gap_service import get_gdp_gap
from app.services.prediction_service import (
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
# MV=PY Model Parameters
# ---------------------------------------------------------------------------

# M3 fallback (trillion yen, approximate 2023 level from FRED MABMM301JPM189S)
_M3_FALLBACK_TRILLION = 1597.0

# US baseline inflation (for PPP exchange rate calculation)
_US_INFLATION_PCT = 2.5


@cached("japan_m3_trillion")
def _get_money_supply() -> float:
    """Fetch Japan M3 money supply (trillion yen) from FRED.

    FRED series MABMM301JPM189S: M3 for Japan, monthly, national currency (yen).
    M3 is broader than M2 and more appropriate for Japan's financial system.
    Divide by 1e12 to convert to trillions.
    Falls back to static constant if fetch fails.
    """
    series = fetch_fred_series("MABMM301JPM189S", years=2)
    if series is not None and len(series) > 0:
        latest_yen = float(series.iloc[-1])
        latest_trillion = round(latest_yen / 1e12, 1)
        if latest_trillion > 0:
            logger.info(
                "Japan M3 from FRED: %.1f trillion yen (latest: %s)",
                latest_trillion,
                series.index[-1].date(),
            )
            return latest_trillion
    logger.info(
        "Japan M3: FRED fetch failed, using fallback %.1f trillion yen",
        _M3_FALLBACK_TRILLION,
    )
    return _M3_FALLBACK_TRILLION


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_mvpy_prediction(
    method: str = "maximum",
    gap_fill_percent: float | None = None,
    uip_sensitivity: float | None = None,
) -> PredictionResponse:
    """MV=PY (貨幣数量説) による予測。

    M x V = P x Y に基づき、財政政策によるGDPギャップ充足が
    流通速度 V を引き上げ、名目GDP・物価・金利・為替に波及する
    メカニズムをモデル化する。

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
    money_supply = _get_money_supply()

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
        logger.exception("Failed to get GDP gap for MV=PY prediction")
        gap_pct = -2.5
        gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)

    # Fiscal spending
    annual_spending = -gap_trillion / FISCAL_MULTIPLIER * effective_gap_fill / 100
    quarterly_spending = annual_spending / 4

    # MV=PY base values
    # V_base = nominal GDP / M
    v_base = nominal_gdp / money_supply if money_supply > 0 else 0.5

    # V change rate driven by gap fill
    # When gap is filled, economic activity increases -> V rises
    # The proportionality: full gap fill of a X% gap raises V by X%
    v_change_rate = effective_gap_fill / 100.0 * abs(gap_pct) / 100.0

    # Real interest rate (Fisher: r_real = i - pi)
    r_real = baseline_jgb - baseline_inflation

    # Resolve UIP sensitivity
    effective_uip = uip_sensitivity if uip_sensitivity is not None else UIP_SENSITIVITY

    # Build quarterly predictions
    quarters = _build_prediction_quarters()
    n_quarters = len(quarters)

    interest_predictions: list[InterestRatePrediction] = []
    exchange_predictions: list[ExchangeRatePrediction] = []
    gdp_impact_predictions: list[GdpImpactPoint] = []
    inflation_predictions: list[InflationPredictionPoint] = []

    # Track cumulative V change for final assumptions
    v_predicted_final = v_base

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

        # Fraction of V change realized at this quarter
        # Proportional to cumulative GDP impact vs full gap fill impact
        max_impact = abs(gap_pct) * effective_gap_fill / 100.0
        if max_impact > 0:
            impact_fraction = min(gdp_impact / max_impact, 1.0) if gdp_impact > 0 else 0.0
        else:
            impact_fraction = 0.0

        # V adjustment
        v_new = v_base * (1.0 + v_change_rate * impact_fraction)
        v_predicted_final = v_new

        # New nominal GDP = M * V_new
        new_nominal_gdp = money_supply * v_new
        # Inflation from MV=PY: price level change
        # P = nominal_GDP / real_GDP
        # Assume real GDP changes by gdp_impact%, so Y_new = Y_base * (1 + gdp_impact/100)
        # P_new = new_nominal_GDP / Y_new
        # inflation = (P_new/P_base - 1) * 100
        y_base = nominal_gdp  # Using nominal as proxy (P_base=1 normalization)
        y_new = y_base * (1.0 + gdp_impact / 100.0)
        if y_new > 0:
            p_ratio = (new_nominal_gdp / y_new) / (nominal_gdp / y_base)
            mvpy_inflation = (p_ratio - 1.0) * 100.0
        else:
            mvpy_inflation = 0.0

        # Total inflation = baseline + MV=PY effect
        predicted_inflation = baseline_inflation + mvpy_inflation

        # Interest rate: Fisher equation
        # i = r_real + expected_inflation
        predicted_rate = r_real + predicted_inflation
        predicted_rate = max(predicted_rate, 0.0)  # ZLB

        # Exchange rate: PPP-based
        # JPY depreciates when Japan inflation > US inflation
        inflation_diff = predicted_inflation - _US_INFLATION_PCT
        # Also incorporate interest rate differential via UIP
        rate_diff = predicted_rate - baseline_jgb
        predicted_fx = baseline_fx + inflation_diff * 2.0 - rate_diff * effective_uip

        interest_predictions.append(
            InterestRatePrediction(
                date=quarters[t],
                predicted_jgb_10y=round(predicted_rate, 2),
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
                predicted_inflation_percent=round(predicted_inflation, 2),
                type="prediction",
            )
        )

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
            model="MV=PY",
            engine="mvpy",
            assumptions=Assumptions(
                fiscal_multiplier=FISCAL_MULTIPLIER,
                nominal_gdp_trillion_yen=nominal_gdp,
                baseline_jgb_10y=baseline_jgb,
                baseline_usdjpy=baseline_fx,
                baseline_inflation=baseline_inflation,
                multiplier_decay_rate=MULTIPLIER_DECAY_RATE,
                money_supply_trillion=round(money_supply, 1),
                velocity_base=round(v_base, 4),
                velocity_predicted=round(v_predicted_final, 4),
            ),
        ),
    )
