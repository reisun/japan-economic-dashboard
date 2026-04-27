"""FastAPI application for Japan Economic Dashboard."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import HealthResponse
from app.routers import fund_demand, gdp_gap, health, inflation, prediction, rates
from app.services.data_utils import fred_available, warn_fred_key_missing_once

# アプリ全体のロガー設定（uvicorn のデフォルトでは app.* の INFO ログが出ないため、
# 明示的にハンドラを app ロガーに付与する）。
# 各サービスの実データ取得成否（real / mock）を運用ログに残すために必要。
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
_app_logger = logging.getLogger("app")
_app_logger.setLevel(_log_level)
# 二重登録を防止
if not any(isinstance(h, logging.StreamHandler) for h in _app_logger.handlers):
    _app_logger.addHandler(_handler)
_app_logger.propagate = False

app = FastAPI(
    title="Japan Economic Dashboard API",
    version="0.1.0",
    description="日本のマクロ経済指標ダッシュボード API",
)

# CORS — allow the Vite dev server and common local origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "https://reisun.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(gdp_gap.router, prefix="/api/v1", tags=["GDP Gap"])
app.include_router(fund_demand.router, prefix="/api/v1", tags=["Fund Demand"])
app.include_router(rates.router, prefix="/api/v1", tags=["Rates"])
app.include_router(prediction.router, prefix="/api/v1", tags=["Prediction"])
app.include_router(inflation.router, prefix="/api/v1", tags=["Inflation"])
app.include_router(health.router, prefix="/api/v1", tags=["Health"])


# 起動時に FRED_API_KEY 未設定なら 1 回だけ警告ログを出す。
# キーが設定されていれば（有効性は実際のリクエスト時に判定する）静かに起動する。
if not fred_available():
    warn_fred_key_missing_once()
else:
    logging.getLogger("app").info(
        "FRED_API_KEY detected; FRED-backed series will be fetched live."
    )


@app.get("/api/v1/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return HealthResponse(status="ok")
