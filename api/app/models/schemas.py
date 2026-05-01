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
    # 在野試算 (高橋洋一・三橋貴明系の代表的レンジに基づく合成系列)
    estimated_civilian: EstimatedGdpGap
    # 後方互換エイリアス: estimated_average と同じ
    estimated: EstimatedGdpGap
    data_status: dict[str, str] | None = None


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
    data_status: dict[str, str] | None = None


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
    fred: list[ExchangeRateDataPoint]


class RatesResponse(BaseModel):
    interest_rates: InterestRates
    exchange_rates: ExchangeRates
    data_status: dict[str, str] | None = None


# ---------- Prediction ----------

class CurrentGap(BaseModel):
    gdp_gap_percent: float
    gdp_gap_trillion_yen: float


class RequiredFiscalSpending(BaseModel):
    amount_trillion_yen: float
    multiplier: float
    note: str = "GDPギャップ充足率に基づく財政支出"
    # GDPギャップの何%を埋める財政政策か (0-150%)
    gap_fill_percent: float = 100.0


class InterestRatePrediction(BaseModel):
    date: str
    predicted_jgb_10y: float
    type: str  # "actual" or "prediction"


class ExchangeRatePrediction(BaseModel):
    date: str
    predicted_usdjpy: float
    type: str  # "actual" or "prediction"


class Assumptions(BaseModel):
    # IS-LM パラメータ（VAR/AR(1) のときは省略）
    money_demand_elasticity: float | None = None
    investment_sensitivity: float | None = None
    fiscal_multiplier: float | None = None
    nominal_gdp_trillion_yen: float | None = None
    uip_sensitivity: float | None = None
    # ベースライン金利（動的取得）
    baseline_jgb_10y: float | None = None
    baseline_usdjpy: float | None = None
    # ゼロ金利制約
    zlb_binding: bool | None = None
    # 乗数減衰率（四半期ごと）
    multiplier_decay_rate: float | None = None
    # フィリップス曲線パラメータ
    phillips_curve_slope: float | None = None  # フィリップス曲線の傾き
    phillips_r_squared: float | None = None  # OLS推定の決定係数
    phillips_n_obs: int | None = None  # OLS推定のサンプル数
    phillips_std_error: float | None = None  # OLS推定の傾き標準誤差
    baseline_inflation: float | None = None  # ベースラインインフレ率
    # 統計モデル用パラメータ
    lag_order: int | None = None
    n_obs: int | None = None
    n_steps: int | None = None
    variables: list[str] | None = None
    # BVAR 用パラメータ
    lambda_tightness: float | None = None
    phillips_prior_slope: float | None = None  # BVAR の CPI 方程式に使った prior α
    implied_phillips_slope: float | None = None  # IRF から逆算した暗黙の α
    # MV=PY (貨幣数量説) 用パラメータ
    money_supply_trillion: float | None = None  # マネーサプライ M2（兆円）
    velocity_base: float | None = None  # ベースライン流通速度 V_base
    velocity_predicted: float | None = None  # 予測流通速度 V_new
    # NKPC (ニューケインジアン・フィリップス曲線) 用パラメータ
    discount_factor: float | None = None  # 割引因子 β
    kappa: float | None = None  # ギャップ感応度 κ
    forward_weight: float | None = None  # 前方視的ウェイト ω
    inflation_target: float | None = None  # インフレ目標 π*


class GdpImpactPoint(BaseModel):
    """GDP影響パスの1点。財政支出によるGDP変化率（ベースラインからの乖離、%）。"""
    date: str
    predicted_gdp_change_percent: float
    type: str = "prediction"  # "actual" | "prediction"


class InflationPredictionPoint(BaseModel):
    """フィリップス曲線に基づくインフレ率予測の1点。"""
    date: str
    predicted_inflation_percent: float
    type: str = "prediction"  # "actual" | "prediction"


class IrfPoint(BaseModel):
    """インパルス応答関数の1点。

    財政支出ショック（外生変数または内生変数）に対する各内生変数の応答。
    """
    horizon: int  # ショックからの四半期数（0=同時期）
    gdp_gap: float | None = None
    jgb_10y: float | None = None
    usdjpy: float | None = None
    cpi_core_core: float | None = None


class ImpactPrediction(BaseModel):
    interest_rate: list[InterestRatePrediction]
    exchange_rate: list[ExchangeRatePrediction]
    gdp_impact: list[GdpImpactPoint]
    inflation_prediction: list[InflationPredictionPoint]
    model: str = "IS-LM"
    # 予測エンジン: "is_lm" | "var" | "ar1"
    engine: str = "is_lm"
    assumptions: Assumptions
    # VAR のみで埋まる: 財政拡張ショック（+1兆円）に対するIRF
    irf: list[IrfPoint] | None = None


class PredictionResponse(BaseModel):
    current_gap: CurrentGap
    required_fiscal_spending: RequiredFiscalSpending
    impact_prediction: ImpactPrediction


# ---------- Inflation ----------

class InflationDataPoint(BaseModel):
    """前年同期比 % で揃えた3系列のインフレ指標。

    CPI は世界標準の core CPI（食料・エネルギー除く基調指標）に対応する
    日本の「コアコア（生鮮食品及びエネルギー除く総合）」を採用。
    """
    date: str
    # CPIコアコア（生鮮食品及びエネルギー除く総合, 前年同月比%）= 世界標準 core CPI
    cpi_core_core: float | None = None
    gdp_deflator: float | None = None    # GDPデフレータ（前年同期比%）
    wage_growth: float | None = None     # 名目賃金（毎月勤労統計, 前年同月比%）


class InflationResponse(BaseModel):
    data: list[InflationDataPoint]
    source: str = "総務省CPI（コアコア） / 内閣府GDPデフレータ / 厚労省毎月勤労統計（モック）"
    boj_target: float = 2.0              # 日銀インフレ目標 2%
    last_updated: str
    data_status: dict[str, str] | None = None


# ---------- Health ----------

class HealthResponse(BaseModel):
    status: str = "ok"
