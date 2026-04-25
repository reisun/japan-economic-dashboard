"""GDP Gap data: Cabinet Office CSV + HP-filter estimation.

Real data source (Cabinet Office):
  https://www5.cao.go.jp/keizai3/getsurei/getsurei-e.html
  The CSV contains quarterly GDP gap estimates.
  Parsing requires handling Shift-JIS encoding and specific column layouts.

For MVP we use mock data and fall back to it when live fetch fails.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np

from app.models.schemas import (
    CabinetOfficeGdpGap,
    EstimatedGdpGap,
    EstimatedGdpGapDataPoint,
    GdpGapDataPoint,
    GdpGapResponse,
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


def _estimate_gdp_gap(
    real_gdp: list[float], quarters: list[str]
) -> list[EstimatedGdpGapDataPoint]:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_gdp_gap() -> GdpGapResponse:
    """Return GDP gap data. Falls back to mock on failure."""
    today = date.today().isoformat()

    # Cabinet Office data — mock for now
    cabinet_data = [GdpGapDataPoint(**d) for d in _MOCK_CABINET_DATA]

    # HP-filter estimation
    try:
        estimated_data = _estimate_gdp_gap(_MOCK_REAL_GDP, _QUARTERS)
    except Exception:
        logger.exception("HP filter estimation failed, using raw mock")
        estimated_data = [
            EstimatedGdpGapDataPoint(
                date=q, real_gdp=g, potential_gdp=g, gdp_gap_percent=0.0
            )
            for q, g in zip(_QUARTERS, _MOCK_REAL_GDP)
        ]

    return GdpGapResponse(
        cabinet_office=CabinetOfficeGdpGap(data=cabinet_data, last_updated=today),
        estimated=EstimatedGdpGap(data=estimated_data, last_updated=today),
    )
