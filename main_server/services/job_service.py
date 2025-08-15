"""Job processing business logic."""

import uuid
import random
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
        jobs = []
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    for _ in range(batch_size):
                        job_id = str(uuid.uuid4())
                        a = random.randint(0, 999)
                        b = random.randint(0, 999)
                        
                        await conn.execute("""
                            INSERT INTO jobs (id, a, b, status, created_at) 
                            VALUES ($1, $2, $3, 'pending', CURRENT_TIMESTAMP)
                        """, job_id, a, b)
                        
                        jobs.append({"id": job_id, "a": a, "b": b})
            
            logger.info("Created new jobs", count=batch_size)
            return {"created": batch_size, "jobs": jobs}
            
        except Exception as e:
            logger.error("Failed to populate jobs", error=str(e))
            raise ValidationError(f"Failed to create jobs: {str(e)}")
    
    async def get_jobs(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get jobs with optional filtering."""
        try:
            async with self.db.get_connection() as conn:
                if status:
                    jobs = await conn.fetch("""
                        SELECT * FROM jobs 
                        WHERE status = $1 
                        ORDER BY created_at DESC 
                        LIMIT $2 OFFSET $3
                    """, status, limit, offset)
                else:
                    jobs = await conn.fetch("""
                        SELECT * FROM jobs 
                        ORDER BY created_at DESC 
                        LIMIT $1 OFFSET $2
                    """, limit, offset)
                
                return [dict(row) for row in jobs]
            
        except Exception as e:
            logger.error("Failed to get jobs", error=str(e))
            raise ValidationError(f"Failed to retrieve jobs: {str(e)}")
    
    async def get_job_by_id(self, job_id: str) -> Dict[str, Any]:
        """Get specific job by ID."""
        try:
            async with self.db.get_connection() as conn:
                job = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
                
                if not job:
                    raise NotFoundError(f"Job {job_id} not found")
                
                return dict(job)
                
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
                    
                    # Find first available job
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
        sum_result = complete_data.sum
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
                    await conn.execute("""
                        INSERT INTO results (id, job_id, a, b, sum, processed_by, processed_at, duration_ms, status)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, 'succeeded')
                    """, result_id, job_id, job_dict['a'], job_dict['b'], sum_result, bot_id, duration_ms)
                    
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
                        "sum": sum_result,
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
                    await conn.execute("""
                        INSERT INTO results (id, job_id, a, b, sum, processed_by, processed_at, duration_ms, status, error)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, 'failed', $8)
                    """, result_id, job_id, job_dict['a'], job_dict['b'], 0, bot_id, 0, error)
                    
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
                        "sum": 0,
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