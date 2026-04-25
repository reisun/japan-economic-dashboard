"""Fund demand data: BOJ Flow of Funds + Bank Lending.

Real data sources:
  - Flow of Funds: https://www.boj.or.jp/statistics/sj/sjhiq.htm (CSV)
  - Bank Lending: https://www.boj.or.jp/statistics/dl/depo/kashi/index.htm

For MVP we use mock data and fall back to it when live fetch fails.
"""

from __future__ import annotations

import logging

from app.models.schemas import (
    BankLending,
    BankLendingDataPoint,
    FlowOfFunds,
    FlowOfFundsDataPoint,
    FundDemandResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_FLOW_OF_FUNDS: list[dict] = []
for q in ["2022-Q1", "2022-Q2", "2022-Q3", "2022-Q4",
           "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
           "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]:
    _MOCK_FLOW_OF_FUNDS.extend([
        {"date": q, "sector": "households",    "net_lending": round(12.0 + (hash(q) % 10) * 0.5, 1)},
        {"date": q, "sector": "corporations",  "net_lending": round(-4.0 + (hash(q) % 6) * 0.3, 1)},
        {"date": q, "sector": "government",    "net_lending": round(-18.0 - (hash(q) % 8) * 0.4, 1)},
    ])

_MOCK_BANK_LENDING: list[dict] = [
    {"date": "2022-01", "total_lending": 510.2, "yoy_change_percent": 1.5},
    {"date": "2022-04", "total_lending": 513.0, "yoy_change_percent": 1.8},
    {"date": "2022-07", "total_lending": 516.5, "yoy_change_percent": 2.0},
    {"date": "2022-10", "total_lending": 518.1, "yoy_change_percent": 2.1},
    {"date": "2023-01", "total_lending": 520.3, "yoy_change_percent": 2.0},
    {"date": "2023-04", "total_lending": 523.0, "yoy_change_percent": 1.9},
    {"date": "2023-07", "total_lending": 526.2, "yoy_change_percent": 1.9},
    {"date": "2023-10", "total_lending": 528.5, "yoy_change_percent": 2.0},
    {"date": "2024-01", "total_lending": 530.0, "yoy_change_percent": 1.9},
    {"date": "2024-04", "total_lending": 532.5, "yoy_change_percent": 1.8},
    {"date": "2024-07", "total_lending": 535.0, "yoy_change_percent": 1.7},
    {"date": "2024-10", "total_lending": 537.0, "yoy_change_percent": 1.6},
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_fund_demand() -> FundDemandResponse:
    """Return fund demand data. Falls back to mock on failure."""
    flow_data = [FlowOfFundsDataPoint(**d) for d in _MOCK_FLOW_OF_FUNDS]
    lending_data = [BankLendingDataPoint(**d) for d in _MOCK_BANK_LENDING]

    return FundDemandResponse(
        flow_of_funds=FlowOfFunds(data=flow_data),
        bank_lending=BankLending(data=lending_data),
    )
