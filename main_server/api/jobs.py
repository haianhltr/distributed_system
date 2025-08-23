"""Job management API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, status, Response

from main_server.models.schemas import (
    JobClaim, JobStart, JobComplete, JobFail, JobPopulate, JobResponse
)
from main_server.services import JobService
from main_server.core.exceptions import (
    NotFoundError, ConflictError, ValidationError, BusinessRuleViolation,
    service_error_handler
)
from .dependencies import get_job_service, verify_admin_token


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/populate", dependencies=[Depends(verify_admin_token)])
async def populate_jobs(
    job_data: JobPopulate,
    job_service: JobService = Depends(get_job_service)
):
    """Create a batch of new jobs."""
    try:
        return await job_service.create_jobs(job_data)
    except ValidationError as e:
        raise service_error_handler(e)


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
        raise service_error_handler(e)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    job_service: JobService = Depends(get_job_service)
):
    """Get specific job by ID."""
    try:
        return await job_service.get_job_by_id(job_id)
    except NotFoundError as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/claim")
async def claim_job(
    claim_data: JobClaim,
    job_service: JobService = Depends(get_job_service),
    response: Response = None
):
    """Atomically claim a job for a bot."""
    try:
        return await job_service.claim_job(claim_data)
    except ConflictError as e:
        raise service_error_handler(e)
    except BusinessRuleViolation as e:
        raise service_error_handler(e)
    except NotFoundError:
        # No jobs available - return 204 No Content
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    except ValidationError as e:
        raise service_error_handler(e)


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
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{job_id}/complete")
async def complete_job(
    job_id: str,
    complete_data: JobComplete,
    job_service: JobService = Depends(get_job_service)
):
    """Mark job as completed successfully."""
    try:
        return await job_service.complete_job(job_id, complete_data)
    except (ConflictError, NotFoundError) as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{job_id}/fail")
async def fail_job(
    job_id: str,
    fail_data: JobFail,
    job_service: JobService = Depends(get_job_service)
):
    """Mark job as failed."""
    try:
        return await job_service.fail_job(job_id, fail_data)
    except (ConflictError, NotFoundError) as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)


@router.post("/{job_id}/release", dependencies=[Depends(verify_admin_token)])
async def release_job(
    job_id: str,
    job_service: JobService = Depends(get_job_service)
):
    """Manually release a stuck job back to pending state."""
    try:
        return await job_service.release_job(job_id)
    except (NotFoundError, BusinessRuleViolation, ConflictError) as e:
        raise service_error_handler(e)
    except ValidationError as e:
        raise service_error_handler(e)