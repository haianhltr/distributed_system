"""Bot management API endpoints."""

from fastapi import APIRouter, Depends, Header
from datetime import datetime

from main_server.models.schemas import BotRegister, BotHeartbeat, BotAssignOperation
from main_server.services import BotService
from main_server.core.exceptions import (
    NotFoundError, ValidationError, ConflictError, 
    service_error_handler
)
from .dependencies import get_bot_service, verify_admin_token, verify_jwt


router = APIRouter(prefix="/bots", tags=["bots"])


@router.post("/register")
async def register_bot(
    bot_data: BotRegister,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    jwt_payload: dict = Depends(verify_jwt),
    bot_service: BotService = Depends(get_bot_service)
):
    """Register a new bot with JWT authentication and idempotency."""
    try:
        # Validate JWT scope
        if jwt_payload.get("scope") != "register":
            raise ValidationError("Invalid JWT scope for registration")
            
        # Call service with idempotency key
        return await bot_service.register_bot(bot_data, idempotency_key)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/heartbeat")
async def bot_heartbeat(
    heartbeat_data: BotHeartbeat,
    bot_service: BotService = Depends(get_bot_service)
):
    """Update bot heartbeat."""
    try:
        return await bot_service.update_heartbeat(heartbeat_data)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.get("")
async def get_bots(
    include_deleted: bool = False,
    bot_service: BotService = Depends(get_bot_service)
):
    """Get all bots with job processing duration and lifecycle status."""
    try:
        return await bot_service.get_bots(include_deleted)
    except ValidationError as e:
        raise service_error_handler(e)


@router.delete("/{bot_id}", dependencies=[Depends(verify_admin_token)])
async def delete_bot(
    bot_id: str,
    bot_service: BotService = Depends(get_bot_service)
):
    """Delete a bot and handle its current job."""
    try:
        return await bot_service.delete_bot(bot_id)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.get("/{bot_id}/stats")
async def get_bot_stats(
    bot_id: str,
    hours: int = 24,
    bot_service: BotService = Depends(get_bot_service)
):
    """Get comprehensive performance stats and history for a bot."""
    try:
        return await bot_service.get_bot_stats(bot_id, hours)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{bot_id}/assign-operation", dependencies=[Depends(verify_admin_token)])
async def assign_bot_operation(
    bot_id: str,
    assignment: BotAssignOperation,
    bot_service: BotService = Depends(get_bot_service)
):
    """Assign an operation to a bot."""
    try:
        return await bot_service.assign_operation(bot_id, assignment)
    except (NotFoundError, ConflictError) as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{bot_id}/reset", dependencies=[Depends(verify_admin_token)])
async def reset_bot_state(
    bot_id: str,
    bot_service: BotService = Depends(get_bot_service)
):
    """Reset bot state to clear stale job assignments."""
    try:
        return await bot_service.reset_bot_state(bot_id)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{bot_id}/restart", dependencies=[Depends(verify_admin_token)])
async def restart_bot(
    bot_id: str,
    bot_service: BotService = Depends(get_bot_service)
):
    """Mark a bot for restart and release any current job."""
    try:
        return await bot_service.restart_bot(bot_id)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/cleanup", dependencies=[Depends(verify_admin_token)])
async def cleanup_dead_bots(
    bot_service: BotService = Depends(get_bot_service)
):
    """Remove bots that have been down for more than 10 minutes."""
    try:
        return await bot_service.cleanup_dead_bots()
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/reset", dependencies=[Depends(verify_admin_token)])
async def reset_bot_states(
    bot_service: BotService = Depends(get_bot_service)
):
    """Reset all bots to idle state and handle their orphaned jobs."""
    try:
        return await bot_service.reset_all_bot_states()
    except ValidationError as e:
        raise service_error_handler(e)