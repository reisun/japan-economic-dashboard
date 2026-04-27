"""Inflation router."""

from fastapi import APIRouter

from app.models.schemas import InflationResponse
from app.services.inflation_service import get_inflation

router = APIRouter()


@router.get("/inflation", response_model=InflationResponse)
async def inflation():
    return await get_inflation()
