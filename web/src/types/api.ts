// GDP Gap types
export interface GdpGapDataPoint {
  date: string;
  gdp_gap_percent: number;
}

export interface GdpGapEstimatedDataPoint {
  date: string;
  real_gdp: number;
  potential_gdp: number;
  gdp_gap_percent: number;
}

export interface EstimatedGdpGapBlock {
  data: GdpGapEstimatedDataPoint[];
  method: string;
  last_updated: string;
}

export interface GdpGapResponse {
  cabinet_office: {
    data: GdpGapDataPoint[];
    source: string;
    last_updated: string;
  };
  estimated_average: EstimatedGdpGapBlock;
  estimated_maximum: EstimatedGdpGapBlock;
  /** 在野試算 (高橋洋一・三橋貴明・藤井聡らの代表的レンジに基づく合成系列) */
  estimated_civilian: EstimatedGdpGapBlock;
  /** 後方互換エイリアス: estimated_average と同じ */
  estimated: EstimatedGdpGapBlock;
  data_status?: Record<string, string>;
}

export type GdpGapMethod = "cabinet_office" | "average" | "maximum" | "civilian";

// Fund Demand types
export interface FlowOfFundsDataPoint {
  date: string;
  sector: string;
  net_lending: number;
}

export interface BankLendingDataPoint {
  date: string;
  total_lending: number;
  yoy_change_percent: number;
}

export interface FundDemandResponse {
  flow_of_funds: {
    data: FlowOfFundsDataPoint[];
    source: string;
    unit: string;
  };
  bank_lending: {
    data: BankLendingDataPoint[];
    source: string;
    unit: string;
  };
  data_status?: Record<string, string>;
}

// Rates types
export interface FredRateDataPoint {
  date: string;
  us_10y_yield: number;
  fed_funds_rate: number;
}

export interface BojRateDataPoint {
  date: string;
  policy_rate: number;
  jgb_10y_yield: number;
}

export interface ExchangeRateDataPoint {
  date: string;
  usdjpy: number;
}

export interface RatesResponse {
  interest_rates: {
    fred: FredRateDataPoint[];
    boj: BojRateDataPoint[];
  };
  exchange_rates: {
    fred: ExchangeRateDataPoint[];
  };
  data_status?: Record<string, string>;
}

// Prediction types
export interface PredictionRatePoint {
  date: string;
  predicted_jgb_10y: number;
  type: "actual" | "prediction";
}

export interface PredictionExchangePoint {
  date: string;
  predicted_usdjpy: number;
  type: "actual" | "prediction";
}

/** 予測エンジン: is_lm (構造) | var (VAR) | ar1 (AR(1) ベンチマーク) */
export type PredictionEngine = "is_lm" | "var" | "ar1";

export interface IrfPoint {
  horizon: number;
  gdp_gap: number | null;
  jgb_10y: number | null;
  usdjpy: number | null;
  cpi_core_core: number | null;
}

export interface PredictionResponse {
  current_gap: {
    gdp_gap_percent: number;
    gdp_gap_trillion_yen: number;
  };
  required_fiscal_spending: {
    amount_trillion_yen: number;
    multiplier: number;
    note: string;
    /** "auto" (GDPギャップから自動算出) | "user" (ユーザー指定シナリオ) */
    scenario_mode?: "auto" | "user";
    /** auto モード時の自動算出値（user モード時の比較表示用） */
    auto_amount_trillion_yen?: number | null;
  };
  impact_prediction: {
    interest_rate: PredictionRatePoint[];
    exchange_rate: PredictionExchangePoint[];
    model: string;
    engine?: PredictionEngine;
    assumptions: {
      money_demand_elasticity?: number | null;
      investment_sensitivity?: number | null;
      fiscal_multiplier?: number | null;
      nominal_gdp_trillion_yen?: number | null;
      uip_sensitivity?: number | null;
      baseline_jgb_10y?: number | null;
      baseline_usdjpy?: number | null;
      zlb_binding?: boolean | null;
      lag_order?: number | null;
      n_obs?: number | null;
      n_steps?: number | null;
      variables?: string[] | null;
    };
    irf?: IrfPoint[] | null;
  };
}

// Inflation types
// CPI は世界標準 core CPI に対応する「コアコア（生鮮食品及びエネルギー除く総合）」
export interface InflationDataPoint {
  date: string;
  cpi_core_core: number | null;
  gdp_deflator: number | null;
  wage_growth: number | null;
}

export interface InflationResponse {
  data: InflationDataPoint[];
  source: string;
  boj_target: number;
  last_updated: string;
  data_status?: Record<string, string>;
}

// Common types
export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}
