"""Data-source health check endpoint.

各外部データソース（FRED / BOJ / e-Stat 等）の最終取得成否と時刻を返す。
secret や生のレスポンス値は含めない。
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from app.services.data_utils import (
    estat_available,
    fred_available,
    get_data_source_status,
)

router = APIRouter()


@router.get("/health/data-sources")
async def health_data_sources() -> dict:
    """データソース取得状況を JSON で返す。

    Response shape:
    {
      "configured": {
        "FRED_API_KEY": true,
        "ESTAT_APP_ID": false
      },
      "sources": {
        "fred:DGS10": {"ok": true, "detail": "points=12", "last_checked": "..."},
        ...
      }
    }
    """
    return {
        "configured": {
            "FRED_API_KEY": fred_available(),
            "ESTAT_APP_ID": estat_available(),
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        },
        "sources": get_data_source_status(),
    }
