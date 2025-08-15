"""Job management API endpoints."""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status

from models.schemas import (
    JobCreate, JobClaim, JobStart, JobComplete, JobFail, JobPopulate
)
from services import JobService
from core.exceptions import NotFoundError, ConflictError, ValidationError
from .dependencies import get_job_service, verify_admin_token


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/populate")
async def populate_jobs(
    job_data: JobPopulate,
    job_service: JobService = Depends(get_job_service),
    token: str = Depends(verify_admin_token)
):
    """Create a batch of new jobs."""
    try:
        return await job_service.create_jobs(job_data)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("")
async def get_jobs(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    job_service: JobService = Depends(get_job_service)
):
    """Get jobs with optional filtering."""
    try:
        return await job_service.get_jobs(status, limit, offset)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    job_service: JobService = Depends(get_job_service)
):
    """Get specific job by ID."""
    try:
        return await job_service.get_job_by_id(job_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/claim")
async def claim_job(
    claim_data: JobClaim,
    job_service: JobService = Depends(get_job_service)
):
    """Atomically claim a job for a bot."""
    try:
        return await job_service.claim_job(claim_data)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT, detail="No jobs available")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{job_id}/start")
async def start_job(
    job_id: str,
    start_data: JobStart,
    job_service: JobService = Depends(get_job_service)
):
    """Mark job as started/processing."""
    try:
        return await job_service.start_job(job_id, start_data)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{job_id}/complete")
async def complete_job(
    job_id: str,
    complete_data: JobComplete,
    job_service: JobService = Depends(get_job_service)
):
    """Mark job as completed successfully."""
    try:
        return await job_service.complete_job(job_id, complete_data)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{job_id}/fail")
async def fail_job(
    job_id: str,
    fail_data: JobFail,
    job_service: JobService = Depends(get_job_service)
):
    """Mark job as failed."""
    try:
        return await job_service.fail_job(job_id, fail_data)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))