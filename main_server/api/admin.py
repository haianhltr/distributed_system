"""Administrative API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import QueryRequest
from services import AdminService
from core.exceptions import ValidationError, AuthenticationError
from .dependencies import get_admin_service, verify_admin_token


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/cleanup")
async def trigger_cleanup(
    dry_run: bool = False,
    admin_service: AdminService = Depends(get_admin_service),
    token: str = Depends(verify_admin_token)
):
    """Manually trigger cleanup of orphaned resources."""
    try:
        return await admin_service.trigger_cleanup(dry_run)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/cleanup/status")
async def get_cleanup_status(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get cleanup service status and configuration."""
    return await admin_service.get_cleanup_status()


@router.post("/query")
async def execute_query(
    query_data: QueryRequest,
    admin_service: AdminService = Depends(get_admin_service),
    token: str = Depends(verify_admin_token)
):
    """Execute a read-only query on the database (admin only)."""
    try:
        return await admin_service.execute_query(query_data)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST if "Only SELECT" in str(e) else status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/recover-jobs")
async def recover_orphaned_jobs(
    admin_service: AdminService = Depends(get_admin_service),
    token: str = Depends(verify_admin_token)
):
    """Recover jobs claimed by dead bots."""
    try:
        return await admin_service.recover_orphaned_jobs()
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))