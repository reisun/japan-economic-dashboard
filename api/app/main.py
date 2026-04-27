"""FastAPI application for Japan Economic Dashboard."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import HealthResponse
from app.routers import fund_demand, gdp_gap, inflation, prediction, rates

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


@app.get("/api/v1/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return HealthResponse(status="ok")
