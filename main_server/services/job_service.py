"""Job processing business logic."""

import random
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from repositories import UnitOfWork, create_unit_of_work
from domain import Job, Result, Operation, JobStatus
from models.schemas import JobPopulate, JobClaim, JobStart, JobComplete, JobFail
from core.exceptions import NotFoundError, ConflictError, ValidationError, BusinessRuleViolation


logger = structlog.get_logger(__name__)


class JobService:
    """Service for job management operations."""
    
    def __init__(self, db_manager: DatabaseManager, datalake_manager: DatalakeManager):
        self.db = db_manager
        self.datalake = datalake_manager
        
    async def create_jobs(self, job_data: JobPopulate) -> Dict[str, Any]:
        """Create a batch of new jobs."""
        batch_size = job_data.batchSize
        operation = job_data.operation or random.choice(['sum', 'subtract', 'multiply', 'divide'])
        
        # Validate operation
        try:
            operation_enum = Operation(operation)
        except ValueError:
            raise ValidationError(f"Invalid operation: {operation}")
        
        jobs_created = []
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                for _ in range(batch_size):
                    a = random.randint(0, 999)
                    # Prevent division by zero
                    b = random.randint(1, 999) if operation == 'divide' else random.randint(0, 999)
                    
                    job_dict = await uow.jobs.create(a, b, operation)
                    jobs_created.append(job_dict)
            
            logger.info("Created new jobs", count=batch_size, operation=operation)
            return {
                "created": batch_size,
                "jobs": jobs_created,
                "operation": operation
            }
            
        except Exception as e:
            logger.error("Failed to populate jobs", error=str(e))
            raise ValidationError(f"Failed to create jobs: {str(e)}")
    
    async def get_jobs(
        self, 
        status: Optional[str] = None, 
        limit: int = 100, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get jobs with optional filtering."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                if status:
                    jobs = await uow.jobs.find_by_status(status, limit, offset)
                else:
                    # Custom query for all jobs with priority sorting
                    query = """
                        SELECT j.*, r.result, r.duration_ms,
                               CASE 
                                   WHEN j.status = 'processing' AND j.started_at IS NOT NULL 
                                   THEN EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 
                                   ELSE NULL 
                               END as processing_duration_minutes
                        FROM jobs j 
                        LEFT JOIN results r ON j.id = r.job_id
                        ORDER BY 
                            CASE j.status
                                WHEN 'pending' THEN 1
                                WHEN 'claimed' THEN 2  
                                WHEN 'processing' THEN 3
                                WHEN 'succeeded' THEN 4
                                WHEN 'failed' THEN 5
                                ELSE 6
                            END,
                            j.created_at DESC
                        LIMIT $1 OFFSET $2
                    """
                    jobs = await uow.jobs.execute_query(query, limit, offset)
                
                # Ensure all fields are present
                for job in jobs:
                    if 'result' not in job:
                        job['result'] = None
                    if 'duration_ms' not in job:
                        job['duration_ms'] = None
                
                return jobs
            
        except Exception as e:
            logger.error("Failed to get jobs", error=str(e))
            raise ValidationError(f"Failed to retrieve jobs: {str(e)}")
    
    async def get_job_by_id(self, job_id: str) -> Dict[str, Any]:
        """Get specific job by ID."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                job = await uow.jobs.find_by_id(job_id)
                
                if not job:
                    raise NotFoundError("Job", job_id)
                
                # Get result if exists
                query = """
                    SELECT result, duration_ms FROM results 
                    WHERE job_id = $1
                """
                results = await uow.results.execute_query(query, job_id)
                
                if results:
                    job['result'] = results[0]['result']
                    job['duration_ms'] = results[0]['duration_ms']
                else:
                    job['result'] = None
                    job['duration_ms'] = None
                
                return job
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to get job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to retrieve job: {str(e)}")
    
    async def claim_job(self, claim_data: JobClaim) -> Dict[str, Any]:
        """Atomically claim a job for a bot."""
        bot_id = claim_data.bot_id
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Check bot state
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                if bot.get('current_job_id'):
                    raise ConflictError("Bot already has an active job")
                
                if not bot.get('assigned_operation'):
                    raise BusinessRuleViolation("Bot has no assigned operation")
                
                # Find available job
                job = await uow.jobs.find_pending_for_operation(
                    bot['assigned_operation'], 
                    limit=1
                )
                
                if not job:
                    raise NotFoundError("No jobs available", "")
                
                # Claim the job
                success = await uow.jobs.claim(job['id'], bot_id)
                if not success:
                    raise ConflictError("Failed to claim job - already claimed")
                
                # Update bot state
                await uow.bots.set_current_job(bot_id, job['id'], 'busy')
                
                return job
                
        except (ConflictError, NotFoundError, BusinessRuleViolation):
            raise
        except Exception as e:
            logger.error("Failed to claim job", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to claim job: {str(e)}")
    
    async def start_job(self, job_id: str, start_data: JobStart) -> Dict[str, str]:
        """Mark job as started/processing."""
        bot_id = start_data.bot_id
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                success = await uow.jobs.start(job_id, bot_id)
                
                if not success:
                    raise ConflictError("Invalid job state or bot mismatch")
                
                return {"status": "started"}
                
        except ConflictError:
            raise
        except Exception as e:
            logger.error("Failed to start job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to start job: {str(e)}")
    
    async def complete_job(self, job_id: str, complete_data: JobComplete) -> Dict[str, str]:
        """Mark job as completed successfully."""
        bot_id = complete_data.bot_id
        result = complete_data.result
        duration_ms = complete_data.duration_ms
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Get job details
                job = await uow.jobs.find_by_id(job_id)
                if not job:
                    raise NotFoundError("Job", job_id)
                
                if job['claimed_by'] != bot_id or job['status'] != 'processing':
                    raise ConflictError("Invalid job state or bot mismatch")
                
                # Mark job as completed
                success = await uow.jobs.complete(job_id, bot_id)
                if not success:
                    raise ConflictError("Failed to complete job")
                
                # Create result record
                result_dict = await uow.results.create(
                    job_id=job_id,
                    a=job['a'],
                    b=job['b'],
                    operation=job['operation'],
                    result=result,
                    processed_by=bot_id,
                    duration_ms=duration_ms,
                    status="succeeded"
                )
                
                # Clear bot's current job
                await uow.bots.set_current_job(bot_id, None, 'idle')
                
                # Write to datalake
                await self.datalake.append_result({
                    "id": result_dict['id'],
                    "job_id": job_id,
                    "a": job['a'],
                    "b": job['b'],
                    "operation": job['operation'],
                    "result": result,
                    "processed_by": bot_id,
                    "processed_at": datetime.utcnow().isoformat(),
                    "duration_ms": duration_ms,
                    "status": "succeeded"
                })
                
                return {"status": "completed"}
                
        except (ConflictError, NotFoundError):
            raise
        except Exception as e:
            logger.error("Failed to complete job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to complete job: {str(e)}")
    
    async def fail_job(self, job_id: str, fail_data: JobFail) -> Dict[str, str]:
        """Mark job as failed."""
        bot_id = fail_data.bot_id
        error = fail_data.error
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Get job details
                job = await uow.jobs.find_by_id(job_id)
                if not job:
                    raise NotFoundError("Job", job_id)
                
                if job['claimed_by'] != bot_id or job['status'] != 'processing':
                    raise ConflictError("Invalid job state or bot mismatch")
                
                # Mark job as failed
                success = await uow.jobs.fail(job_id, bot_id, error)
                if not success:
                    raise ConflictError("Failed to fail job")
                
                # Create result record
                result_dict = await uow.results.create(
                    job_id=job_id,
                    a=job['a'],
                    b=job['b'],
                    operation=job['operation'],
                    result=0,
                    processed_by=bot_id,
                    duration_ms=0,
                    status="failed",
                    error=error
                )
                
                # Clear bot's current job
                await uow.bots.set_current_job(bot_id, None, 'idle')
                
                # Write to datalake
                await self.datalake.append_result({
                    "id": result_dict['id'],
                    "job_id": job_id,
                    "a": job['a'],
                    "b": job['b'],
                    "operation": job['operation'],
                    "result": 0,
                    "processed_by": bot_id,
                    "processed_at": datetime.utcnow().isoformat(),
                    "duration_ms": 0,
                    "status": "failed",
                    "error": error
                })
                
                return {"status": "failed"}
                
        except (ConflictError, NotFoundError):
            raise
        except Exception as e:
            logger.error("Failed to fail job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to fail job: {str(e)}")
    
    async def release_job(self, job_id: str) -> Dict[str, Any]:
        """Release a stuck job back to pending state."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                job = await uow.jobs.find_by_id(job_id)
                if not job:
                    raise NotFoundError("Job", job_id)
                
                if job['status'] not in ['claimed', 'processing']:
                    raise BusinessRuleViolation(
                        f"Job {job_id} is in {job['status']} state and cannot be released"
                    )
                
                # Release job
                success = await uow.jobs.release_to_pending(job_id)
                if not success:
                    raise ConflictError("Failed to release job")
                
                # Reset bot if assigned
                if job['claimed_by']:
                    bot = await uow.bots.find_by_id(job['claimed_by'])
                    if bot and bot.get('current_job_id') == job_id:
                        await uow.bots.set_current_job(job['claimed_by'], None, 'idle')
                
                logger.info(f"Released job {job_id} back to pending")
                
                return {
                    "status": "released",
                    "job_id": job_id,
                    "bot_id": job.get('claimed_by'),
                    "message": f"Job {job_id} has been released back to pending state"
                }
                
        except (NotFoundError, BusinessRuleViolation, ConflictError):
            raise
        except Exception as e:
            logger.error(f"Failed to release job {job_id}: {e}")
            raise ValidationError(f"Failed to release job: {str(e)}")
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get job system metrics."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                job_metrics = await uow.jobs.get_metrics()
                throughput = await uow.results.get_system_throughput(hours=1)
                
                return {
                    "jobs": job_metrics,
                    "throughput": {
                        "completed_last_hour": throughput
                    }
                }
                
        except Exception as e:
            logger.error("Failed to get job metrics", error=str(e))
            raise ValidationError(f"Failed to get metrics: {str(e)}")