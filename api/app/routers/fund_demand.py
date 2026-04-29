"""Fund Demand router."""

from fastapi import APIRouter

from app.models.schemas import (
    BankLendingDataPoint,
    FlowOfFundsDataPoint,
    FundDemandResponse,
)
from app.services.data_utils import monthly_to_yearly, quarterly_fof_to_yearly
from app.services.fund_demand_service import get_fund_demand

router = APIRouter()


@router.get("/fund-demand", response_model=FundDemandResponse)
async def fund_demand():
    resp = await get_fund_demand()

    # Aggregate to yearly at the router level.
    # Bank lending (date is "YYYY-MM" format)
    lending_dicts = [d.model_dump() for d in resp.bank_lending.data]
    yearly_lending = monthly_to_yearly(
        lending_dicts, ["total_lending", "yoy_change_percent"]
    )
    resp.bank_lending.data = [BankLendingDataPoint(**d) for d in yearly_lending]

    # Flow of funds (date is "YYYY-Qn" format, with sector grouping)
    fof_dicts = [d.model_dump() for d in resp.flow_of_funds.data]
    yearly_fof = quarterly_fof_to_yearly(
        fof_dicts, ["net_lending"], group_field="sector"
    )
    resp.flow_of_funds.data = [FlowOfFundsDataPoint(**d) for d in yearly_fof]

    return resp
