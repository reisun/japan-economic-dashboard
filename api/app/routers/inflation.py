"""Inflation router."""

from fastapi import APIRouter

from app.models.schemas import InflationDataPoint, InflationResponse
from app.services.data_utils import quarterly_to_yearly
from app.services.inflation_service import get_inflation

router = APIRouter()

_VALUE_FIELDS = ["cpi_core_core", "gdp_deflator", "wage_growth"]


@router.get("/inflation", response_model=InflationResponse)
async def inflation():
    resp = await get_inflation()

    # Aggregate to yearly at the router level.
    dicts = [d.model_dump() for d in resp.data]
    yearly = quarterly_to_yearly(dicts, _VALUE_FIELDS)
    resp.data = [InflationDataPoint(**d) for d in yearly]

    return resp
