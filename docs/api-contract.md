# API Contract

## Base URL
`http://localhost:8000/api/v1`

## Endpoints

### 1. GDP Gap
`GET /gdp-gap`

Response:
```json
{
  "cabinet_office": {
    "data": [
      {"date": "2020-Q1", "gdp_gap_percent": -3.2}
    ],
    "source": "内閣府",
    "last_updated": "2024-01-01"
  },
  "estimated": {
    "data": [
      {"date": "2020-Q1", "real_gdp": 530.5, "potential_gdp": 548.0, "gdp_gap_percent": -3.19}
    ],
    "method": "HP Filter",
    "last_updated": "2024-01-01"
  }
}
```

### 2. Fund Demand
`GET /fund-demand`

Response:
```json
{
  "flow_of_funds": {
    "data": [
      {"date": "2020-Q1", "sector": "households", "net_lending": 15.2},
      {"date": "2020-Q1", "sector": "corporations", "net_lending": -5.3},
      {"date": "2020-Q1", "sector": "government", "net_lending": -20.1}
    ],
    "source": "日銀資金循環統計",
    "unit": "兆円"
  },
  "bank_lending": {
    "data": [
      {"date": "2020-01", "total_lending": 520.3, "yoy_change_percent": 2.1}
    ],
    "source": "日銀貸出統計",
    "unit": "兆円"
  }
}
```

### 3. Interest Rates & Exchange Rates
`GET /rates`

Response:
```json
{
  "interest_rates": {
    "fred": [
      {"date": "2020-01-01", "us_10y_yield": 1.88, "fed_funds_rate": 1.75}
    ],
    "boj": [
      {"date": "2020-01-01", "policy_rate": -0.10, "jgb_10y_yield": 0.01}
    ]
  },
  "exchange_rates": {
    "fred": [
      {"date": "2020-01-01", "usdjpy": 108.5}
    ]
  }
}
```

### 4. Prediction (IS-LM Model)
`GET /prediction`

Query parameters:
- `method` (optional): `cabinet_office | average | maximum | civilian` — どの GDP ギャップ推計を起点にするか（既定: `maximum`）
- `fiscal_spending_trillion` (optional, float): 任意の財政支出額（兆円, 符号付き）。指定時はこの値で IS-LM インパクトを計算する。範囲 `-200`〜`200`、範囲外は HTTP 400。未指定時は GDP ギャップから自動算出。

Response:
```json
{
  "current_gap": {
    "gdp_gap_percent": -2.5,
    "gdp_gap_trillion_yen": -14.0
  },
  "required_fiscal_spending": {
    "amount_trillion_yen": 14.0,
    "multiplier": 1.0,
    "note": "デフレギャップ解消に必要な財政支出",
    "scenario_mode": "auto",
    "auto_amount_trillion_yen": 14.0
  },
  "impact_prediction": {
    "interest_rate": [
      {"date": "2025-Q1", "predicted_jgb_10y": 0.85, "type": "actual"},
      {"date": "2025-Q2", "predicted_jgb_10y": 0.95, "type": "prediction"},
      {"date": "2025-Q3", "predicted_jgb_10y": 1.10, "type": "prediction"},
      {"date": "2025-Q4", "predicted_jgb_10y": 1.20, "type": "prediction"}
    ],
    "exchange_rate": [
      {"date": "2025-Q1", "predicted_usdjpy": 150.0, "type": "actual"},
      {"date": "2025-Q2", "predicted_usdjpy": 148.5, "type": "prediction"},
      {"date": "2025-Q3", "predicted_usdjpy": 146.0, "type": "prediction"},
      {"date": "2025-Q4", "predicted_usdjpy": 144.0, "type": "prediction"}
    ],
    "model": "IS-LM",
    "assumptions": {
      "money_demand_elasticity": 0.5,
      "investment_sensitivity": 0.3,
      "fiscal_multiplier": 1.0
    }
  }
}
```

### 5. Health Check
`GET /health`

Response:
```json
{"status": "ok"}
```
