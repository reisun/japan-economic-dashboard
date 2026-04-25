"""Prediction (IS-LM model) router."""

from fastapi import APIRouter

from app.models.schemas import PredictionResponse
from app.services.prediction_service import get_prediction

router = APIRouter()


@router.get("/prediction", response_model=PredictionResponse)
async def prediction():
    return await get_prediction()
