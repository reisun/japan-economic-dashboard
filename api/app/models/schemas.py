"""Pydantic models matching the API contract."""

from __future__ import annotations

from pydantic import BaseModel


# ---------- GDP Gap ----------

class GdpGapDataPoint(BaseModel):
    date: str
    gdp_gap_percent: float


class EstimatedGdpGapDataPoint(BaseModel):
    date: str
    real_gdp: float
    potential_gdp: float
    gdp_gap_percent: float


class CabinetOfficeGdpGap(BaseModel):
    data: list[GdpGapDataPoint]
    source: str = "内閣府"
    last_updated: str


class EstimatedGdpGap(BaseModel):
    data: list[EstimatedGdpGapDataPoint]
    method: str = "HP Filter"
    last_updated: str


class GdpGapResponse(BaseModel):
    cabinet_office: CabinetOfficeGdpGap
    # 平均概念（HPフィルター）
    estimated_average: EstimatedGdpGap
    # 最大概念（直接推計; MVP=正残差75%タイル）
    estimated_maximum: EstimatedGdpGap
    # 後方互換エイリアス: estimated_average と同じ
    estimated: EstimatedGdpGap


# ---------- Fund Demand ----------

class FlowOfFundsDataPoint(BaseModel):
    date: str
    sector: str
    net_lending: float


class BankLendingDataPoint(BaseModel):
    date: str
    total_lending: float
    yoy_change_percent: float


class FlowOfFunds(BaseModel):
    data: list[FlowOfFundsDataPoint]
    source: str = "日銀資金循環統計"
    unit: str = "兆円"


class BankLending(BaseModel):
    data: list[BankLendingDataPoint]
    source: str = "日銀貸出統計"
    unit: str = "兆円"


class FundDemandResponse(BaseModel):
    flow_of_funds: FlowOfFunds
    bank_lending: BankLending


# ---------- Rates ----------

class FredRateDataPoint(BaseModel):
    date: str
    us_10y_yield: float | None = None
    fed_funds_rate: float | None = None


class BojRateDataPoint(BaseModel):
    date: str
    policy_rate: float | None = None
    jgb_10y_yield: float | None = None


class ExchangeRateDataPoint(BaseModel):
    date: str
    usdjpy: float


class InterestRates(BaseModel):
    fred: list[FredRateDataPoint]
    boj: list[BojRateDataPoint]


class ExchangeRates(BaseModel):
    yahoo_finance: list[ExchangeRateDataPoint]
    fred: list[ExchangeRateDataPoint]


class RatesResponse(BaseModel):
    interest_rates: InterestRates
    exchange_rates: ExchangeRates


# ---------- Prediction ----------

class CurrentGap(BaseModel):
    gdp_gap_percent: float
    gdp_gap_trillion_yen: float


class RequiredFiscalSpending(BaseModel):
    amount_trillion_yen: float
    multiplier: float
    note: str = "デフレギャップ解消に必要な財政支出"


class InterestRatePrediction(BaseModel):
    date: str
    predicted_jgb_10y: float
    type: str  # "actual" or "prediction"


class ExchangeRatePrediction(BaseModel):
    date: str
    predicted_usdjpy: float
    type: str  # "actual" or "prediction"


class Assumptions(BaseModel):
    money_demand_elasticity: float
    investment_sensitivity: float
    fiscal_multiplier: float


class ImpactPrediction(BaseModel):
    interest_rate: list[InterestRatePrediction]
    exchange_rate: list[ExchangeRatePrediction]
    model: str = "IS-LM"
    assumptions: Assumptions


class PredictionResponse(BaseModel):
    current_gap: CurrentGap
    required_fiscal_spending: RequiredFiscalSpending
    impact_prediction: ImpactPrediction


# ---------- Health ----------

class HealthResponse(BaseModel):
    status: str = "ok"
