"""Shared constants and utility functions for prediction services.

Extracted from prediction_service.py to break circular dependencies between
prediction_service and var_service / mvpy_service / nkpc_service.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import numpy as np

from app.models.schemas import GdpGapResponse
from app.services.cache import cached
from app.services.data_utils import fetch_fred_series

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Fiscal multiplier: dY/dG
FISCAL_MULTIPLIER = 1.0

# Multiplier decay rate per quarter (half-life ~ 4 quarters)
MULTIPLIER_DECAY_RATE = 0.85

# UIP sensitivity: how much JPY appreciates per 1pp rise in JGB yield
# (simplified: higher domestic rates -> stronger yen)
UIP_SENSITIVITY = 2.0  # yen per percentage point

# Default gap fill percentage
DEFAULT_GAP_FILL_PERCENT = 100.0

# Valid GDP gap estimation methods
VALID_METHODS = ("cabinet_office", "average", "maximum", "civilian")

# Prediction horizon
PREDICTION_YEARS_AHEAD = 2

# Nominal GDP fallback (trillion yen)
_NOMINAL_GDP_FALLBACK = 560.0

# Current baseline interest rates (fallback when live fetch fails)
BASELINE_JGB_10Y = 0.85  # percent
BASELINE_USDJPY = 150.0

# Phillips curve slope: sensitivity of inflation to GDP gap (percentage points)
# Japan's empirical range is 0.1-0.5; 0.3 is a reasonable central estimate
PHILLIPS_CURVE_SLOPE = 0.3  # fallback when OLS estimation fails

# ---------------------------------------------------------------------------
# Phillips curve slope OLS estimation (per method, cached)
# ---------------------------------------------------------------------------

# Simple dict-based TTL cache for method-keyed results
_phillips_cache: dict[str, tuple[float, tuple[float, float | None, int, float | None]]] = {}
_PHILLIPS_CACHE_TTL = 3600  # 1 hour

PhillipsSlopeResult = tuple[float, float | None, int, float | None]
# (slope, r_squared, n_obs, std_error)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


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


@cached("baseline_inflation")
def _get_baseline_inflation() -> float:
    """Get latest CPI core-core YoY as baseline inflation.

    Fetches from inflation_service and returns the most recent value.
    Falls back to 2.0% if unavailable.
    """
    try:
        from app.services.inflation_service import _fetch_cpi_core_core_yoy

        cpi_q = _fetch_cpi_core_core_yoy()
        if cpi_q:
            latest_q = max(cpi_q.keys())
            val = cpi_q[latest_q]
            logger.info("Baseline inflation from CPI core-core: %.1f%% (%s)", val, latest_q)
            return val
    except Exception:
        logger.exception("Failed to fetch baseline inflation")
    logger.info("Baseline inflation: using fallback 2.0%%")
    return 2.0


def _ols_slope(
    gaps: np.ndarray, cpis: np.ndarray
) -> tuple[float, float, float | None]:
    """OLS: CPI = beta0 + alpha * gap.

    Returns (alpha, r_squared, std_error).
    """
    n = len(gaps)
    X = np.column_stack([np.ones(n), gaps])
    # beta = (X'X)^-1 X'y
    XtX = X.T @ X
    Xty = X.T @ cpis
    beta = np.linalg.solve(XtX, Xty)
    alpha = float(beta[1])

    # Residuals and R-squared
    y_hat = X @ beta
    residuals = cpis - y_hat
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((cpis - np.mean(cpis)) ** 2))
    r_squared = round(1.0 - ss_res / ss_tot, 4) if ss_tot > 0 else 0.0

    # Standard error of alpha
    if n > 2:
        mse = ss_res / (n - 2)
        var_beta = mse * np.linalg.inv(XtX)
        std_error = round(float(np.sqrt(var_beta[1, 1])), 4)
    else:
        std_error = None

    alpha = round(alpha, 4)
    return (alpha, r_squared, std_error)


def _estimate_phillips_slope(
    method: str,
    gdp_gap_data: GdpGapResponse | None,
) -> PhillipsSlopeResult:
    """Estimate Phillips curve slope via OLS for the given GDP gap method.

    Regression: CPI_yoy = beta0 + alpha * GDP_gap + epsilon
    Returns (alpha, R-squared, n_obs, std_error_of_alpha).
    Falls back to (0.3, None, 0, None) on failure.
    """
    now = time.monotonic()
    cache_key = method
    if cache_key in _phillips_cache:
        expires_at, result = _phillips_cache[cache_key]
        if now < expires_at:
            return result

    fallback: PhillipsSlopeResult = (PHILLIPS_CURVE_SLOPE, None, 0, None)

    if gdp_gap_data is None:
        logger.warning("Phillips slope estimation: GDP gap data unavailable, using fallback")
        return fallback

    try:
        from app.services.inflation_service import _fetch_cpi_core_core_yoy

        # Get CPI quarterly data
        cpi_q = _fetch_cpi_core_core_yoy()
        if not cpi_q:
            logger.warning("Phillips slope estimation: CPI data unavailable, using fallback")
            return fallback

        # Get GDP gap series for the given method
        if method == "cabinet_office":
            gap_series = gdp_gap_data.cabinet_office.data
        elif method == "average":
            gap_series = gdp_gap_data.estimated_average.data
        elif method == "civilian":
            gap_series = gdp_gap_data.estimated_civilian.data
        else:  # maximum
            gap_series = gdp_gap_data.estimated_maximum.data

        gap_q = {pt.date: pt.gdp_gap_percent for pt in gap_series}

        # Build paired data for common quarters
        common_quarters = sorted(
            set(gap_q.keys()) & set(cpi_q.keys()),
        )
        if len(common_quarters) < 3:
            logger.warning(
                "Phillips slope estimation: only %d common quarters, need >= 3, using fallback",
                len(common_quarters),
            )
            return fallback

        gaps = np.array([gap_q[q] for q in common_quarters])
        cpis = np.array([cpi_q[q] for q in common_quarters])
        n = len(gaps)

        alpha, r_squared, std_error = _ols_slope(gaps, cpis)

        logger.info(
            "Phillips slope estimated (method=%s): alpha=%.4f, R2=%.4f, n=%d, se=%.4f",
            method,
            alpha,
            r_squared,
            n,
            std_error if std_error is not None else 0.0,
        )

        result = (alpha, r_squared, n, std_error)
        _phillips_cache[cache_key] = (now + _PHILLIPS_CACHE_TTL, result)
        return result

    except Exception:
        logger.exception("Phillips slope estimation failed, using fallback")
        return fallback


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


def _build_spending_note(amount: float, gap_fill_percent: float) -> str:
    """Generate summary text for spending display."""
    if amount > 0:
        return f"GDPギャップの{gap_fill_percent:.0f}%充足: 拡張的財政支出 {amount:+.1f}兆円/年"
    if amount < 0:
        return f"GDPギャップの{gap_fill_percent:.0f}%充足: 財政引き締め {amount:+.1f}兆円/年"
    return "財政中立（インパクトなし）"
