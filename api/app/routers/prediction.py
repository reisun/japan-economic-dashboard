"""Prediction (IS-LM model) router."""

from fastapi import APIRouter, Query

from app.models.schemas import PredictionResponse
from app.services.prediction_service import VALID_METHODS, get_prediction

router = APIRouter()


@router.get("/prediction", response_model=PredictionResponse)
async def prediction(
    method: str = Query(
        "maximum",
        description="GDPギャップ推計手法: cabinet_office | average | maximum",
    ),
):
    if method not in VALID_METHODS:
        method = "maximum"
    return await get_prediction(method=method)
