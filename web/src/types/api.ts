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
  /** 後方互換エイリアス: estimated_average と同じ */
  estimated: EstimatedGdpGapBlock;
}

export type GdpGapMethod = "cabinet_office" | "average" | "maximum";

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
    yahoo_finance: ExchangeRateDataPoint[];
    fred: ExchangeRateDataPoint[];
  };
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

export interface PredictionResponse {
  current_gap: {
    gdp_gap_percent: number;
    gdp_gap_trillion_yen: number;
  };
  required_fiscal_spending: {
    amount_trillion_yen: number;
    multiplier: number;
    note: string;
  };
  impact_prediction: {
    interest_rate: PredictionRatePoint[];
    exchange_rate: PredictionExchangePoint[];
    model: string;
    assumptions: {
      money_demand_elasticity: number;
      investment_sensitivity: number;
      fiscal_multiplier: number;
    };
  };
}

// Common types
export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}
