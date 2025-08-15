"""Metrics and monitoring API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from services import MetricsService
from core.exceptions import ValidationError
from .dependencies import get_metrics_service


router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_simple_metrics(
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """Simple JSON metrics endpoint."""
    return await metrics_service.get_simple_metrics()


@router.get("/metrics/summary")
async def get_metrics_summary(
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """Get system metrics summary for dashboard."""
    try:
        return await metrics_service.get_metrics_summary()
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/datalake/stats")
async def get_datalake_stats(
    days: int = 7,
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """Get datalake statistics."""
    try:
        return await metrics_service.get_datalake_stats(days)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/datalake/export/{date}")
async def export_datalake_date(
    date: str,
    metrics_service: MetricsService = Depends(get_metrics_service)
):
    """Export datalake data for a specific date."""
    try:
        return await metrics_service.export_datalake_date(date)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))