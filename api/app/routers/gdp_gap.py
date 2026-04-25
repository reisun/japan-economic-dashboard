"""GDP Gap router."""

from fastapi import APIRouter

from app.models.schemas import GdpGapResponse
from app.services.gdp_gap_service import get_gdp_gap

router = APIRouter()


@router.get("/gdp-gap", response_model=GdpGapResponse)
async def gdp_gap():
    return await get_gdp_gap()
