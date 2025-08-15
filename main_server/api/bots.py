"""Bot management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import BotRegister, BotHeartbeat
from services import BotService
from core.exceptions import NotFoundError, ValidationError
from .dependencies import get_bot_service, verify_admin_token


router = APIRouter(prefix="/bots", tags=["bots"])


@router.post("/register")
async def register_bot(
    bot_data: BotRegister,
    bot_service: BotService = Depends(get_bot_service)
):
    """Register a new bot."""
    try:
        return await bot_service.register_bot(bot_data)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/heartbeat")
async def bot_heartbeat(
    heartbeat_data: BotHeartbeat,
    bot_service: BotService = Depends(get_bot_service)
):
    """Update bot heartbeat."""
    try:
        return await bot_service.update_heartbeat(heartbeat_data)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("")
async def get_bots(
    include_deleted: bool = False,
    bot_service: BotService = Depends(get_bot_service)
):
    """Get all bots with job processing duration and lifecycle status."""
    try:
        return await bot_service.get_bots(include_deleted)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: str,
    bot_service: BotService = Depends(get_bot_service),
    token: str = Depends(verify_admin_token)
):
    """Delete a bot and handle its current job."""
    try:
        return await bot_service.delete_bot(bot_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{bot_id}/stats")
async def get_bot_stats(
    bot_id: str,
    hours: int = 24,
    bot_service: BotService = Depends(get_bot_service)
):
    """Get comprehensive performance stats and history for a bot."""
    try:
        return await bot_service.get_bot_stats(bot_id, hours)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{bot_id}/reset")
async def reset_bot_state(
    bot_id: str,
    bot_service: BotService = Depends(get_bot_service),
    token: str = Depends(verify_admin_token)
):
    """Reset bot state to clear stale job assignments."""
    try:
        return await bot_service.reset_bot_state(bot_id)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/cleanup")
async def cleanup_dead_bots(
    bot_service: BotService = Depends(get_bot_service),
    token: str = Depends(verify_admin_token)
):
    """Remove bots that have been down for more than 10 minutes."""
    try:
        return await bot_service.cleanup_dead_bots()
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/reset")
async def reset_bot_states(
    bot_service: BotService = Depends(get_bot_service),
    token: str = Depends(verify_admin_token)
):
    """Reset all bots to idle state and handle their orphaned jobs."""
    try:
        return await bot_service.reset_all_bot_states()
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))