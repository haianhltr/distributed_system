"""Job processing business logic."""

import uuid
import random
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from models.schemas import JobCreate, JobClaim, JobStart, JobComplete, JobFail, JobPopulate
from core.exceptions import NotFoundError, ConflictError, ValidationError


logger = structlog.get_logger(__name__)


class JobService:
    """Service for job management operations."""
    
    def __init__(self, db_manager: DatabaseManager, datalake_manager: DatalakeManager):
        self.db = db_manager
        self.datalake = datalake_manager
        
    async def create_jobs(self, job_data: JobPopulate) -> Dict[str, Any]:
        """Create a batch of new jobs."""
        batch_size = job_data.batchSize
        operation = job_data.operation  # Get operation from request
        jobs = []
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    for _ in range(batch_size):
                        job_id = str(uuid.uuid4())
                        a = random.randint(0, 999)
                        
                        # Handle division by zero prevention
                        if operation == 'divide':
                            b = random.randint(1, 999)  # Avoid b = 0
                        else:
                            b = random.randint(0, 999)
                        
                        # FIXED: Include operation field in INSERT
                        await conn.execute("""
                            INSERT INTO jobs (id, a, b, operation, status, created_at) 
                            VALUES ($1, $2, $3, $4, 'pending', CURRENT_TIMESTAMP)
                        """, job_id, a, b, operation)
                        
                        # FIXED: Include operation in response
                        jobs.append({"id": job_id, "a": a, "b": b, "operation": operation})
            
            logger.info("Created new jobs", count=batch_size, operation=operation)
            return {"created": batch_size, "jobs": jobs, "operation": operation}
            
        except Exception as e:
            logger.error("Failed to populate jobs", error=str(e))
            raise ValidationError(f"Failed to create jobs: {str(e)}")
    
    async def get_jobs(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get jobs with optional filtering."""
        try:
            async with self.db.get_connection() as conn:
                if status:
                    jobs = await conn.fetch("""
                        SELECT j.*, r.result, r.duration_ms,
                               CASE 
                                   WHEN j.status = 'processing' AND j.started_at IS NOT NULL 
                                   THEN EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 
                                   ELSE NULL 
                               END as processing_duration_minutes
                        FROM jobs j 
                        LEFT JOIN results r ON j.id = r.job_id
                        WHERE j.status = $1 
                        ORDER BY j.created_at DESC 
                        LIMIT $2 OFFSET $3
                    """, status, limit, offset)
                else:
                    # Priority sorting: pending/claimed/processing first, then completed/failed
                    # Within each priority group, sort by created_at DESC
                    jobs = await conn.fetch("""
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
                    """, limit, offset)
                
                # Convert to dict and ensure all fields are included
                job_list = []
                for row in jobs:
                    job_dict = dict(row)
                    # Explicitly handle result and duration_ms fields
                    if 'result' not in job_dict:
                        job_dict['result'] = None
                    if 'duration_ms' not in job_dict:
                        job_dict['duration_ms'] = None
                    job_list.append(job_dict)
                
                return job_list
            
        except Exception as e:
            logger.error("Failed to get jobs", error=str(e))
            raise ValidationError(f"Failed to retrieve jobs: {str(e)}")
    
    async def get_job_by_id(self, job_id: str) -> Dict[str, Any]:
        """Get specific job by ID."""
        try:
            async with self.db.get_connection() as conn:
                job = await conn.fetchrow("""
                    SELECT j.*, r.result, r.duration_ms,
                           CASE 
                               WHEN j.status = 'processing' AND j.started_at IS NOT NULL 
                               THEN EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 
                               ELSE NULL 
                           END as processing_duration_minutes
                    FROM jobs j 
                    LEFT JOIN results r ON j.id = r.job_id
                    WHERE j.id = $1
                """, job_id)
                
                if not job:
                    raise NotFoundError(f"Job {job_id} not found")
                
                # Convert to dict and ensure all fields are included
                job_dict = dict(job)
                # Explicitly handle result and duration_ms fields
                if 'result' not in job_dict:
                    job_dict['result'] = None
                if 'duration_ms' not in job_dict:
                    job_dict['duration_ms'] = None
                    
                return job_dict
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to get job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to retrieve job: {str(e)}")
    
    async def claim_job(self, claim_data: JobClaim) -> Dict[str, Any]:
        """Atomically claim a job for a bot."""
        bot_id = claim_data.bot_id
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Check if bot already has a job
                    existing_job = await conn.fetchval("""
                        SELECT current_job_id FROM bots 
                        WHERE id = $1 AND current_job_id IS NOT NULL
                    """, bot_id)
                    
                    if existing_job:
                        raise ConflictError("Bot already has an active job")
                    
                    # Get bot's assigned operation
                    bot_operation = await conn.fetchval("""
                        SELECT assigned_operation FROM bots WHERE id = $1
                    """, bot_id)
                    
                    # Find first available job matching bot's operation (or any if unassigned)
                    if bot_operation:
                        # Bot has assigned operation - only claim jobs of that type
                        available_job = await conn.fetchrow("""
                            SELECT * FROM jobs 
                            WHERE status = 'pending' AND operation = $1
                            ORDER BY created_at ASC 
                            LIMIT 1
                        """, bot_operation)
                    else:
                        # Bot has no assigned operation - can claim any job
                        available_job = await conn.fetchrow("""
                            SELECT * FROM jobs 
                            WHERE status = 'pending' 
                            ORDER BY created_at ASC 
                            LIMIT 1
                        """)
                    
                    if not available_job:
                        raise NotFoundError("No jobs available")
                    
                    job_dict = dict(available_job)
                    
                    # Claim the job
                    await conn.execute("""
                        UPDATE jobs 
                        SET status = 'claimed', claimed_by = $1, claimed_at = NOW()
                        WHERE id = $2 AND status = 'pending'
                    """, bot_id, job_dict['id'])
                    
                    # Update bot's current job
                    await conn.execute("""
                        UPDATE bots 
                        SET current_job_id = $1, status = 'busy'
                        WHERE id = $2
                    """, job_dict['id'], bot_id)
                    
                    return job_dict
                
        except (ConflictError, NotFoundError):
            raise
        except Exception as e:
            logger.error("Failed to claim job", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to claim job: {str(e)}")
    
    async def start_job(self, job_id: str, start_data: JobStart) -> Dict[str, str]:
        """Mark job as started/processing."""
        bot_id = start_data.bot_id
        
        try:
            async with self.db.get_connection() as conn:
                result = await conn.execute("""
                    UPDATE jobs 
                    SET status = 'processing', started_at = NOW()
                    WHERE id = $1 AND claimed_by = $2 AND status = 'claimed'
                """, job_id, bot_id)
                
                if result == 'UPDATE 0':
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
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Get job details
                    job = await conn.fetchrow("""
                        SELECT * FROM jobs 
                        WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
                    """, job_id, bot_id)
                    
                    if not job:
                        raise ConflictError("Invalid job state or bot mismatch")
                    
                    job_dict = dict(job)
                    
                    # Mark job as succeeded
                    await conn.execute("""
                        UPDATE jobs 
                        SET status = 'succeeded', finished_at = NOW()
                        WHERE id = $1
                    """, job_id)
                    
                    # Create result record
                    result_id = str(uuid.uuid4())
                    # Only populate sum column for sum operations
                    sum_value = result if job_dict['operation'] == 'sum' else None
                    
                    # Prepare JSONB data for new generic schema
                    input_data = {
                        "a": job_dict['a'],
                        "b": job_dict['b']
                    }
                    output_data = {
                        "result": result
                    }
                    metadata = {
                        "operation_type": job_dict['operation'],
                        "execution_context": "distributed_bot",
                        "legacy_mode": True
                    }
                    
                    await conn.execute("""
                        INSERT INTO results (id, job_id, a, b, sum, result, operation, processed_by, processed_at, duration_ms, status, input_data, output_data, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10, $11, $12, $13)
                    """, result_id, job_id, job_dict['a'], job_dict['b'], sum_value, result, job_dict['operation'], bot_id, duration_ms, 
                    'succeeded', input_data, output_data, metadata)
                    
                    # Clear bot's current job
                    await conn.execute("""
                        UPDATE bots 
                        SET current_job_id = NULL, status = 'idle'
                        WHERE id = $1
                    """, bot_id)
                    
                    # Write to datalake
                    await self.datalake.append_result({
                        "id": result_id,
                        "job_id": job_id,
                        "a": job_dict['a'],
                        "b": job_dict['b'],
                        "result": result,
                        "operation": job_dict['operation'],
                        "processed_by": bot_id,
                        "processed_at": datetime.utcnow().isoformat(),
                        "duration_ms": duration_ms,
                        "status": "succeeded"
                    })
                    
                    return {"status": "completed"}
                
        except ConflictError:
            raise
        except Exception as e:
            logger.error("Failed to complete job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to complete job: {str(e)}")
    
    async def fail_job(self, job_id: str, fail_data: JobFail) -> Dict[str, str]:
        """Mark job as failed."""
        bot_id = fail_data.bot_id
        error = fail_data.error
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Get job details
                    job = await conn.fetchrow("""
                        SELECT * FROM jobs 
                        WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
                    """, job_id, bot_id)
                    
                    if not job:
                        raise ConflictError("Invalid job state or bot mismatch")
                    
                    job_dict = dict(job)
                    
                    # Mark job as failed
                    await conn.execute("""
                        UPDATE jobs 
                        SET status = 'failed', finished_at = NOW(), attempts = attempts + 1, error = $1
                        WHERE id = $2
                    """, error, job_id)
                    
                    # Create result record  
                    result_id = str(uuid.uuid4())
                    
                    # Prepare JSONB data for new generic schema
                    input_data = {
                        "a": job_dict['a'],
                        "b": job_dict['b']
                    }
                    output_data = {
                        "error": error,
                        "result": None
                    }
                    metadata = {
                        "operation_type": job_dict['operation'],
                        "execution_context": "distributed_bot",
                        "legacy_mode": True,
                        "failure_reason": error
                    }
                    
                    await conn.execute("""
                        INSERT INTO results (id, job_id, a, b, sum, result, operation, processed_by, processed_at, duration_ms, status, error, input_data, output_data, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10, $11, $12, $13, $14)
                    """, result_id, job_id, job_dict['a'], job_dict['b'], None, 0, job_dict['operation'], bot_id, 0, 
                    'failed', error, input_data, output_data, metadata)
                    
                    # Clear bot's current job
                    await conn.execute("""
                        UPDATE bots 
                        SET current_job_id = NULL, status = 'idle'
                        WHERE id = $1
                    """, bot_id)
                    
                    # Write to datalake
                    await self.datalake.append_result({
                        "id": result_id,
                        "job_id": job_id,
                        "a": job_dict['a'],
                        "b": job_dict['b'],
                        "result": 0,
                        "operation": job_dict['operation'],
                        "processed_by": bot_id,
                        "processed_at": datetime.utcnow().isoformat(),
                        "duration_ms": 0,
                        "status": "failed",
                        "error": error
                    })
                    
                    return {"status": "failed"}
                
        except ConflictError:
            raise
        except Exception as e:
            logger.error("Failed to fail job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to fail job: {str(e)}")