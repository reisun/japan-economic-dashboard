"""Prediction (IS-LM model) router."""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import PredictionResponse
from app.services.prediction_service import (
    FISCAL_SPENDING_MAX,
    FISCAL_SPENDING_MIN,
    VALID_METHODS,
    get_prediction,
)

router = APIRouter()


VALID_ENGINES = ("is_lm", "var", "ar1")


@router.get("/prediction", response_model=PredictionResponse)
async def prediction(
    method: str = Query(
        "maximum",
        description="GDPギャップ推計手法: cabinet_office | average | maximum | civilian",
    ),
    fiscal_spending_trillion: float | None = Query(
        None,
        description=(
            "任意の財政支出額（兆円）。指定時はこの値でインパクトを計算する。"
            "未指定時は GDP ギャップから自動算出。"
            f"範囲: {FISCAL_SPENDING_MIN}〜{FISCAL_SPENDING_MAX}"
        ),
    ),
    engine: str = Query(
        "is_lm",
        description=(
            "予測エンジン: is_lm (構造モデル, デフォルト) | var (Vector Autoregression) | "
            "ar1 (AR(1) ベンチマーク)"
        ),
    ),
    uip_sensitivity: float | None = Query(
        None,
        description=(
            "UIP感応度（円/pp）。JGB金利1%p上昇あたりの円高幅。"
            "未指定時はデフォルト値 2.0 を使用。範囲: 0〜10"
        ),
        ge=0.0,
        le=10.0,
    ),
):
    if method not in VALID_METHODS:
        method = "maximum"
    if engine not in VALID_ENGINES:
        engine = "is_lm"
    if fiscal_spending_trillion is not None:
        if (
            fiscal_spending_trillion < FISCAL_SPENDING_MIN
            or fiscal_spending_trillion > FISCAL_SPENDING_MAX
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "fiscal_spending_trillion は "
                    f"{FISCAL_SPENDING_MIN}〜{FISCAL_SPENDING_MAX} の範囲で指定してください"
                ),
            )
    return await get_prediction(
        method=method,
        fiscal_spending_trillion=fiscal_spending_trillion,
        engine=engine,
        uip_sensitivity=uip_sensitivity,
    )
