"""Interest Rates & Exchange Rates router."""

from fastapi import APIRouter

from app.models.schemas import (
    BojRateDataPoint,
    ExchangeRateDataPoint,
    FredRateDataPoint,
    RatesResponse,
)
from app.services.data_utils import monthly_to_yearly
from app.services.rates_service import get_rates

router = APIRouter()


@router.get("/rates", response_model=RatesResponse)
async def rates():
    resp = await get_rates()

    # Aggregate to yearly at the router level.
    # FRED rates
    fred_dicts = [d.model_dump() for d in resp.interest_rates.fred]
    yearly_fred = monthly_to_yearly(fred_dicts, ["us_10y_yield", "fed_funds_rate"])
    resp.interest_rates.fred = [FredRateDataPoint(**d) for d in yearly_fred]

    # BOJ rates
    boj_dicts = [d.model_dump() for d in resp.interest_rates.boj]
    yearly_boj = monthly_to_yearly(boj_dicts, ["policy_rate", "jgb_10y_yield"])
    resp.interest_rates.boj = [BojRateDataPoint(**d) for d in yearly_boj]

    # FRED FX
    fred_fx_dicts = [d.model_dump() for d in resp.exchange_rates.fred]
    yearly_fred_fx = monthly_to_yearly(fred_fx_dicts, ["usdjpy"])
    resp.exchange_rates.fred = [ExchangeRateDataPoint(**d) for d in yearly_fred_fx]

    return resp
