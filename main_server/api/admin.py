"""Administrative API endpoints."""

from fastapi import APIRouter, Depends

from main_server.models.schemas import QueryRequest
from main_server.services import AdminService
from main_server.core.exceptions import (
    ValidationError, BusinessRuleViolation, 
    service_error_handler
)
from .dependencies import get_admin_service, verify_admin_token


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_token)])


@router.post("/cleanup")
async def trigger_cleanup(
    dry_run: bool = False,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Manually trigger cleanup of orphaned resources."""
    try:
        return await admin_service.trigger_cleanup(dry_run)
    except ValidationError as e:
        raise service_error_handler(e)


@router.get("/cleanup/status")
async def get_cleanup_status(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get cleanup service status and configuration."""
    try:
        return await admin_service.get_cleanup_status()
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/query")
async def execute_query(
    query_data: QueryRequest,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Execute a read-only query on the database (admin only)."""
    try:
        return await admin_service.execute_query(query_data)
    except BusinessRuleViolation as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.get("/stuck-jobs")
async def get_stuck_jobs(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get summary of potentially stuck jobs."""
    try:
        return await admin_service.get_stuck_jobs()
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/cleanup-inconsistent-states")
async def cleanup_inconsistent_states(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Clean up inconsistent bot-job states."""
    try:
        return await admin_service.cleanup_inconsistent_states()
    except ValidationError as e:
        raise service_error_handler(e)