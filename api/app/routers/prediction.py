"""Prediction (IS-LM model) router."""

from fastapi import APIRouter, Query

from app.models.schemas import PredictionResponse
from app.services.prediction_service import (
    VALID_METHODS,
    get_prediction,
)

router = APIRouter()


VALID_ENGINES = ("is_lm", "var", "ar1", "bvar", "rw", "mvpy", "nkpc")


@router.get("/prediction", response_model=PredictionResponse)
async def prediction(
    method: str = Query(
        "maximum",
        description="GDPギャップ推計手法: cabinet_office | average | maximum | civilian",
    ),
    gap_fill_percent: float = Query(
        100.0,
        description="GDPギャップの何%を埋める財政政策を想定するか（0〜150%）",
        ge=0.0,
        le=150.0,
    ),
    engine: str = Query(
        "is_lm",
        description=(
            "予測エンジン: is_lm (構造モデル, デフォルト) | var (VAR) | "
            "bvar (Bayesian VAR) | ar1 (AR(1)) | rw (Random Walk) | "
            "mvpy (MV=PY 貨幣数量説) | nkpc (NKフィリップス曲線)"
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
    return await get_prediction(
        method=method,
        gap_fill_percent=gap_fill_percent,
        engine=engine,
        uip_sensitivity=uip_sensitivity,
    )
