"""GDP Gap router."""

from fastapi import APIRouter

from app.models.schemas import (
    CabinetOfficeGdpGap,
    EstimatedGdpGap,
    EstimatedGdpGapDataPoint,
    GdpGapDataPoint,
    GdpGapResponse,
)
from app.services.data_utils import quarterly_to_yearly
from app.services.gdp_gap_service import get_gdp_gap

router = APIRouter()

_SIMPLE_FIELDS = ["gdp_gap_percent"]
_ESTIMATED_FIELDS = ["real_gdp", "potential_gdp", "gdp_gap_percent"]


def _yearly_simple(data: list[GdpGapDataPoint]) -> list[GdpGapDataPoint]:
    """Convert quarterly GdpGapDataPoint list to yearly."""
    dicts = [d.model_dump() for d in data]
    yearly = quarterly_to_yearly(dicts, _SIMPLE_FIELDS)
    return [GdpGapDataPoint(**d) for d in yearly]


def _yearly_estimated(data: list[EstimatedGdpGapDataPoint]) -> list[EstimatedGdpGapDataPoint]:
    """Convert quarterly EstimatedGdpGapDataPoint list to yearly."""
    dicts = [d.model_dump() for d in data]
    yearly = quarterly_to_yearly(dicts, _ESTIMATED_FIELDS)
    return [EstimatedGdpGapDataPoint(**d) for d in yearly]


@router.get("/gdp-gap", response_model=GdpGapResponse)
async def gdp_gap():
    resp = await get_gdp_gap()

    # Aggregate to yearly at the router level.
    # Service functions keep returning quarterly data for prediction_service.
    resp.cabinet_office.data = _yearly_simple(resp.cabinet_office.data)
    resp.estimated_average.data = _yearly_estimated(resp.estimated_average.data)
    resp.estimated_maximum.data = _yearly_estimated(resp.estimated_maximum.data)
    resp.estimated_civilian.data = _yearly_estimated(resp.estimated_civilian.data)
    resp.estimated.data = _yearly_estimated(resp.estimated.data)

    return resp
