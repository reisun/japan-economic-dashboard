"""Interest Rates & Exchange Rates router."""

from fastapi import APIRouter

from app.models.schemas import RatesResponse
from app.services.rates_service import get_rates

router = APIRouter()


@router.get("/rates", response_model=RatesResponse)
async def rates():
    return await get_rates()
