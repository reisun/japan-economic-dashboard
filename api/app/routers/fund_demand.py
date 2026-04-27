"""Fund Demand router."""

from fastapi import APIRouter

from app.models.schemas import FundDemandResponse
from app.services.fund_demand_service import get_fund_demand

router = APIRouter()


@router.get("/fund-demand", response_model=FundDemandResponse)
async def fund_demand():
    return await get_fund_demand()
