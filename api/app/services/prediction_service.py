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
from datetime import date

from app.models.schemas import (
    Assumptions,
    CurrentGap,
    ExchangeRatePrediction,
    ImpactPrediction,
    InterestRatePrediction,
    PredictionResponse,
    RequiredFiscalSpending,
)
from app.services.cache import cached
from app.services.data_utils import fetch_fred_series
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

# Nominal GDP fallback (trillion yen)
_NOMINAL_GDP_FALLBACK = 560.0


@cached("nominal_gdp_trillion")
def _get_nominal_gdp() -> float:
    """Fetch latest Japan nominal GDP (trillion yen) from FRED.

    FRED series JPNNGDP: quarterly, seasonally adjusted annual rate,
    in billions of yen. Divide by 1000 to convert to trillions.
    Falls back to the static constant if fetch fails.
    """
    series = fetch_fred_series("JPNNGDP", years=2)
    if series is not None and len(series) > 0:
        latest_billion = float(series.iloc[-1])
        latest_trillion = round(latest_billion / 1000.0, 1)
        logger.info(
            "Nominal GDP from FRED: %.1f trillion yen (latest: %s)",
            latest_trillion,
            series.index[-1].date(),
        )
        return latest_trillion
    logger.info(
        "Nominal GDP: FRED fetch failed, using fallback %.1f trillion yen",
        _NOMINAL_GDP_FALLBACK,
    )
    return _NOMINAL_GDP_FALLBACK

# Current baseline interest rates (fallback when live fetch fails)
BASELINE_JGB_10Y = 0.85  # percent
BASELINE_USDJPY = 150.0

# Zero Lower Bound for JGB 10Y nominal rate (percent)
ZLB_RATE = 0.0

# UIP sensitivity: how much JPY appreciates per 1pp rise in JGB yield
# (simplified: higher domestic rates → stronger yen)
UIP_SENSITIVITY = 2.0  # yen per percentage point

PREDICTION_YEARS_AHEAD = 2


@cached("latest_rates_for_prediction")
def _get_latest_rates() -> tuple[float, float]:
    """Fetch latest JGB 10Y and USD/JPY from the rates service.

    Uses FRED BOJ rates for JGB 10Y and FRED FX for USD/JPY.
    Falls back to hardcoded constants if fetch fails.
    Returns (jgb_10y_percent, usdjpy).
    """
    try:
        from app.services.rates_service import _fetch_boj_rates, _fetch_fred_fx

        jgb = BASELINE_JGB_10Y
        fx = BASELINE_USDJPY

        boj_rates = _fetch_boj_rates()
        if boj_rates:
            for pt in reversed(boj_rates):
                if pt.jgb_10y_yield is not None:
                    jgb = pt.jgb_10y_yield
                    break

        fred_fx = _fetch_fred_fx()
        if fred_fx:
            fx = fred_fx[-1].usdjpy

        logger.info(
            "Dynamic baselines: JGB 10Y=%.2f%%, USD/JPY=%.1f",
            jgb,
            fx,
        )
        return (jgb, fx)
    except Exception:
        logger.exception(
            "Failed to fetch dynamic baselines, using fallbacks"
        )
        return (BASELINE_JGB_10Y, BASELINE_USDJPY)


# シナリオ入力の範囲（兆円）
FISCAL_SPENDING_MIN = -200.0
FISCAL_SPENDING_MAX = 200.0


def _build_prediction_quarters() -> list[str]:
    today = date.today()
    current_q = (today.month - 1) // 3 + 1
    current_y = today.year
    total = PREDICTION_YEARS_AHEAD * 4 + 1  # current quarter + 8 ahead
    quarters: list[str] = []
    y, q = current_y, current_q
    for _ in range(total):
        quarters.append(f"{y}-Q{q}")
        q += 1
        if q > 4:
            q = 1
            y += 1
    return quarters


# ---------------------------------------------------------------------------
# IS-LM calculation
# ---------------------------------------------------------------------------


def _compute_is_lm_impact(
    fiscal_spending_trillion: float,
    n_quarters: int,
    nominal_gdp: float,
    baseline_jgb: float = BASELINE_JGB_10Y,
    baseline_fx: float = BASELINE_USDJPY,
    uip_sensitivity: float = UIP_SENSITIVITY,
) -> tuple[list[float], list[float], bool]:
    """Compute predicted interest rates and exchange rates per quarter.

    Returns (jgb_10y_list, usdjpy_list, zlb_binding) for each quarter.
    The ZLB constraint clamps the nominal rate at ZLB_RATE and adjusts
    the effective dr for UIP accordingly (liquidity trap behavior).
    """
    n = n_quarters

    # Total interest rate impact from fiscal expansion (percentage points)
    total_dr = (
        fiscal_spending_trillion
        * FISCAL_MULTIPLIER
        * MONEY_DEMAND_ELASTICITY
        / (INVESTMENT_SENSITIVITY + MONEY_DEMAND_ELASTICITY)
        / nominal_gdp
        * 100
    )

    # Phase in: 0% at Q1 (actual), then ramp to 100% by Q5, hold steady after
    ramp_quarters = 4
    phase_in = [0.0] + [
        min(1.0, i / ramp_quarters) for i in range(1, n)
    ]

    jgb_rates: list[float] = []
    usdjpy_rates: list[float] = []
    zlb_binding = False

    for frac in phase_in:
        dr = total_dr * frac
        r = baseline_jgb + dr

        # Zero Lower Bound constraint
        if r < ZLB_RATE:
            r = ZLB_RATE
            zlb_binding = True
            # Effective dr for UIP is based on clamped rate
            effective_dr = ZLB_RATE - baseline_jgb
        else:
            effective_dr = dr

        r = round(r, 2)
        # UIP: higher domestic rate → yen appreciation (lower USD/JPY)
        fx = round(baseline_fx - effective_dr * uip_sensitivity, 1)
        jgb_rates.append(r)
        usdjpy_rates.append(fx)

    return jgb_rates, usdjpy_rates, zlb_binding


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


VALID_METHODS = ("cabinet_office", "average", "maximum", "civilian")


def _build_spending_note(amount: float, scenario_mode: str) -> str:
    """サマリー表示用の文言を生成する。"""
    if scenario_mode == "user":
        if amount > 0:
            return f"ユーザー指定シナリオ: 拡張的財政支出 {amount:+.1f}兆円"
        if amount < 0:
            return f"ユーザー指定シナリオ: 財政引き締め {amount:+.1f}兆円"
        return "ユーザー指定シナリオ: 財政中立（インパクトなし）"
    # auto
    if amount >= 0:
        return "デフレギャップ解消に必要な財政支出"
    return "インフレギャップ抑制に必要な財政引き締め"


async def get_prediction(
    method: str = "maximum",
    fiscal_spending_trillion: float | None = None,
    engine: str = "is_lm",
    uip_sensitivity: float | None = None,
) -> PredictionResponse:
    """予測モデル切替対応のディスパッチャ。

    engine = "is_lm" (デフォルト, 構造モデル) / "var" / "ar1" を選択可能。
    """
    if engine == "var":
        from app.services.var_service import get_var_prediction

        return await get_var_prediction(
            method=method, fiscal_spending_trillion=fiscal_spending_trillion
        )
    if engine == "ar1":
        from app.services.var_service import get_ar1_prediction

        return await get_ar1_prediction(
            method=method, fiscal_spending_trillion=fiscal_spending_trillion
        )

    # IS-LM (デフォルト)
    if method not in VALID_METHODS:
        method = "maximum"

    # Fetch dynamic nominal GDP
    nominal_gdp = _get_nominal_gdp()

    # Fetch dynamic baseline rates
    baseline_jgb, baseline_fx = _get_latest_rates()

    # Get latest GDP gap estimate
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

    # Required fiscal spending to close the gap.
    # 需給ギャップ < 0 (デフレ): 拡張的財政支出が必要 → 正の値
    # 需給ギャップ > 0 (過熱): 引き締め的財政運営が必要 → 負の値
    # 符号付きで返し、IS-LM の金利・為替インパクトもこの符号に応じて方向付けする。
    auto_required_spending = -gap_trillion / FISCAL_MULTIPLIER

    # ユーザー指定があればそちらを優先（任意のシナリオ入力）
    if fiscal_spending_trillion is not None:
        required_spending = float(fiscal_spending_trillion)
        scenario_mode = "user"
    else:
        required_spending = auto_required_spending
        scenario_mode = "auto"

    # Resolve effective UIP sensitivity
    effective_uip = uip_sensitivity if uip_sensitivity is not None else UIP_SENSITIVITY

    # IS-LM impact
    quarters = _build_prediction_quarters()
    jgb_rates, usdjpy_rates, zlb_binding = _compute_is_lm_impact(
        required_spending,
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

    return PredictionResponse(
        current_gap=CurrentGap(
            gdp_gap_percent=gap_pct,
            gdp_gap_trillion_yen=gap_trillion,
        ),
        required_fiscal_spending=RequiredFiscalSpending(
            amount_trillion_yen=round(required_spending, 1),
            multiplier=FISCAL_MULTIPLIER,
            note=(
                _build_spending_note(required_spending, scenario_mode)
            ),
            scenario_mode=scenario_mode,
            auto_amount_trillion_yen=round(auto_required_spending, 1),
        ),
        impact_prediction=ImpactPrediction(
            interest_rate=interest_predictions,
            exchange_rate=exchange_predictions,
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
            ),
        ),
    )
