import asyncio
import json
import uuid
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from cleanup_service import CleanupService, CleanupScheduler

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

def format_duration(seconds):
    """Format duration in seconds to human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

app = FastAPI(title="Distributed Job Processing System", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()


# Configuration
class Config:
    POPULATE_INTERVAL_MS = int(os.environ.get("POPULATE_INTERVAL_MS", str(10 * 60 * 1000)))  # 10 minutes
    BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin-secret-token")
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ds_user:ds_password@localhost:5432/distributed_system")
    DATALAKE_PATH = os.environ.get("DATALAKE_PATH", "datalake/data")

config = Config()

# Initialize database and datalake
db_manager = DatabaseManager(config.DATABASE_URL)
datalake = DatalakeManager(config.DATALAKE_PATH)

# Initialize cleanup service
cleanup_service = CleanupService(db_manager)
cleanup_scheduler = CleanupScheduler(cleanup_service)


# Pydantic models
class JobCreate(BaseModel):
    a: int
    b: int

class JobClaim(BaseModel):
    bot_id: str

class JobStart(BaseModel):
    bot_id: str

class JobComplete(BaseModel):
    bot_id: str
    sum: int
    duration_ms: int

class JobFail(BaseModel):
    bot_id: str
    error: str

class BotRegister(BaseModel):
    bot_id: str

class BotHeartbeat(BaseModel):
    bot_id: str

class JobPopulate(BaseModel):
    batchSize: int = 5

class ScaleUp(BaseModel):
    count: int = 1

# Admin authentication
async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    return credentials.credentials

# Health check
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Simple metrics endpoint (replaces Prometheus)
@app.get("/metrics")
async def get_simple_metrics():
    """Simple JSON metrics endpoint"""
    try:
        async with db_manager.get_connection() as conn:
            # Count jobs by status
            job_counts = await conn.fetch("""
                SELECT status, COUNT(*) as count 
                FROM jobs 
                GROUP BY status
            """)
            
            # Count bots by status
            bot_counts = await conn.fetch("""
                SELECT 
                    CASE 
                        WHEN deleted_at IS NOT NULL THEN 'deleted'
                        WHEN NOW() - INTERVAL '2 minutes' > last_heartbeat_at THEN 'down'
                        ELSE status
                    END as computed_status,
                    COUNT(*) as count
                FROM bots 
                GROUP BY computed_status
            """)
            
            # Total counts
            total_jobs = await conn.fetchval("SELECT COUNT(*) FROM jobs")
            total_bots = await conn.fetchval("SELECT COUNT(*) FROM bots WHERE deleted_at IS NULL")
            
            # Recent activity
            jobs_last_hour = await conn.fetchval("""
                SELECT COUNT(*) FROM jobs 
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """)
            
            # Build metrics response
            metrics = {
                "timestamp": datetime.utcnow().isoformat(),
                "jobs": {
                    "total": total_jobs or 0,
                    "by_status": {row["status"]: row["count"] for row in job_counts}
                },
                "bots": {
                    "total": total_bots or 0,
                    "by_status": {row["computed_status"]: row["count"] for row in bot_counts}
                },
                "activity": {
                    "jobs_created_last_hour": jobs_last_hour or 0
                }
            }
            
            return metrics
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "error": "Failed to retrieve metrics",
            "jobs": {"total": 0, "by_status": {}},
            "bots": {"total": 0, "by_status": {}},
            "activity": {"jobs_created_last_hour": 0}
        }

# Job endpoints
@app.post("/jobs/populate")
async def populate_jobs(
    job_data: JobPopulate,
    token: str = Depends(verify_admin_token)
):
    """Create a batch of new jobs"""
    batch_size = job_data.batchSize
    jobs = []
    
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                for i in range(batch_size):
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
        raise HTTPException(status_code=500, detail="Failed to create jobs")

@app.get("/jobs")
async def get_jobs(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """Get jobs with optional filtering"""
    try:
        async with db_manager.get_connection() as conn:
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
        logger.error(f"Failed to get jobs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve jobs")

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get specific job by ID"""
    try:
        async with db_manager.get_connection() as conn:
            job = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
            
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            return dict(job)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve job")

@app.post("/jobs/claim")
async def claim_job(claim_data: JobClaim):
    """Atomically claim a job for a bot"""
    bot_id = claim_data.bot_id
    
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Check if bot already has a job
                existing_job = await conn.fetchval("""
                    SELECT current_job_id FROM bots 
                    WHERE id = $1 AND current_job_id IS NOT NULL
                """, bot_id)
                
                if existing_job:
                    raise HTTPException(status_code=409, detail="Bot already has an active job")
                
                # Find first available job
                available_job = await conn.fetchrow("""
                    SELECT * FROM jobs 
                    WHERE status = 'pending' 
                    ORDER BY created_at ASC 
                    LIMIT 1
                """)
                
                if not available_job:
                    raise HTTPException(status_code=204, detail="No jobs available")
                
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
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to claim job for bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to claim job")

@app.post("/jobs/{job_id}/start")
async def start_job(job_id: str, start_data: JobStart):
    """Mark job as started/processing"""
    bot_id = start_data.bot_id
    
    try:
        async with db_manager.get_connection() as conn:
            result = await conn.execute("""
                UPDATE jobs 
                SET status = 'processing', started_at = NOW()
                WHERE id = $1 AND claimed_by = $2 AND status = 'claimed'
            """, job_id, bot_id)
            
            if result == 'UPDATE 0':
                raise HTTPException(status_code=409, detail="Invalid job state or bot mismatch")
            
            return {"status": "started"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to start job")

@app.post("/jobs/{job_id}/complete")
async def complete_job(job_id: str, complete_data: JobComplete):
    """Mark job as completed successfully"""
    bot_id = complete_data.bot_id
    sum_result = complete_data.sum
    duration_ms = complete_data.duration_ms
    
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Get job details
                job = await conn.fetchrow("""
                    SELECT * FROM jobs 
                    WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
                """, job_id, bot_id)
                
                if not job:
                    raise HTTPException(status_code=409, detail="Invalid job state or bot mismatch")
                
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
                await datalake.append_result({
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
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete job")

@app.post("/jobs/{job_id}/fail")
async def fail_job(job_id: str, fail_data: JobFail):
    """Mark job as failed"""
    bot_id = fail_data.bot_id
    error = fail_data.error
    
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Get job details
                job = await conn.fetchrow("""
                    SELECT * FROM jobs 
                    WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
                """, job_id, bot_id)
                
                if not job:
                    raise HTTPException(status_code=409, detail="Invalid job state or bot mismatch")
                
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
                await datalake.append_result({
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
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fail job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fail job")

# Bot endpoints
@app.post("/bots/cleanup")
async def cleanup_dead_bots(token: str = Depends(verify_admin_token)):
    """Remove bots that have been down for more than 10 minutes"""
    try:
        async with db_manager.get_connection() as conn:
            result = await conn.execute("""
                UPDATE bots 
                SET deleted_at = NOW() 
                WHERE last_heartbeat_at < NOW() - INTERVAL '10 minutes'
                AND deleted_at IS NULL
            """)
            
            count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
            logger.info(f"Cleaned up {count} dead bots")
            return {"cleaned_up": count, "status": "success"}
            
    except Exception as e:
        logger.error(f"Failed to cleanup dead bots: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup bots")

@app.post("/bots/reset")
async def reset_bot_states(token: str = Depends(verify_admin_token)):
    """Reset all bots to idle state and handle their orphaned jobs"""
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Get all bots with current jobs
                bots_with_jobs = await conn.fetch("""
                    SELECT id, current_job_id FROM bots 
                    WHERE current_job_id IS NOT NULL AND deleted_at IS NULL
                """)
                
                reset_count = 0
                for bot in bots_with_jobs:
                    bot_id = bot['id']
                    job_id = bot['current_job_id']
                    
                    # Check job status
                    job = await conn.fetchrow("SELECT status FROM jobs WHERE id = $1", job_id)
                    
                    if job:
                        if job['status'] in ['claimed', 'processing']:
                            # Return job to pending if it was claimed/processing
                            await conn.execute("""
                                UPDATE jobs 
                                SET status = 'pending', claimed_by = NULL, claimed_at = NULL, started_at = NULL
                                WHERE id = $1
                            """, job_id)
                            logger.info(f"Reset job {job_id} to pending")
                    
                    # Clear bot's current job and set to idle
                    await conn.execute("""
                        UPDATE bots 
                        SET current_job_id = NULL, status = 'idle'
                        WHERE id = $1
                    """, bot_id)
                    
                    reset_count += 1
                    logger.info(f"Reset bot {bot_id} to idle")
                
                return {"reset_bots": reset_count, "status": "success"}
                
    except Exception as e:
        logger.error(f"Failed to reset bot states: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset bot states")

@app.post("/bots/register")
async def register_bot(bot_data: BotRegister):
    """Register a new bot"""
    bot_id = bot_data.bot_id
    
    try:
        async with db_manager.get_connection() as conn:
            await conn.execute("""
                INSERT INTO bots (id, status, last_heartbeat_at, created_at)
                VALUES ($1, 'idle', NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    status = 'idle',
                    last_heartbeat_at = NOW(),
                    deleted_at = NULL
            """, bot_id)
        
        logger.info(f"Bot registered: {bot_id}")
        return {"status": "registered", "bot_id": bot_id}
        
    except Exception as e:
        logger.error(f"Failed to register bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.post("/bots/heartbeat")
async def bot_heartbeat(heartbeat_data: BotHeartbeat):
    """Update bot heartbeat"""
    bot_id = heartbeat_data.bot_id
    
    try:
        async with db_manager.get_connection() as conn:
            result = await conn.execute("""
                UPDATE bots 
                SET last_heartbeat_at = NOW()
                WHERE id = $1 AND deleted_at IS NULL
            """, bot_id)
            
            if result == 'UPDATE 0':
                raise HTTPException(status_code=404, detail="Bot not found or deleted")
            
            return {"status": "ok"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update heartbeat for bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update heartbeat")

@app.get("/bots")
async def get_bots(include_deleted: bool = False):
    """Get all bots with job processing duration and lifecycle status"""
    try:
        async with db_manager.get_connection() as conn:
            # Base query that includes all bots
            where_clause = "" if include_deleted else "WHERE b.deleted_at IS NULL"
            
            bots = await conn.fetch(f"""
                SELECT b.*, 
                       CASE 
                           WHEN b.deleted_at IS NOT NULL THEN 'deleted'
                           WHEN NOW() - INTERVAL '2 minutes' > b.last_heartbeat_at THEN 'down'
                           ELSE b.status
                       END as computed_status,
                       CASE 
                           WHEN b.deleted_at IS NOT NULL THEN 'deleted'
                           WHEN NOW() - INTERVAL '2 minutes' > b.last_heartbeat_at THEN 'stale'
                           ELSE 'active'
                       END as lifecycle_status,
                       j.started_at,
                       EXTRACT(EPOCH FROM (NOW() - j.started_at)) as processing_duration_seconds,
                       EXTRACT(EPOCH FROM (NOW() - b.last_heartbeat_at)) as seconds_since_heartbeat,
                       EXTRACT(EPOCH FROM (NOW() - b.deleted_at)) as seconds_since_deleted
                FROM bots b
                LEFT JOIN jobs j ON b.current_job_id = j.id AND j.status = 'processing'
                {where_clause}
                ORDER BY 
                    CASE WHEN b.deleted_at IS NULL THEN 0 ELSE 1 END,
                    b.last_heartbeat_at DESC NULLS LAST,
                    b.created_at DESC
            """)
            
            result = []
            for bot in bots:
                bot_dict = dict(bot)
                
                # Format processing duration
                if bot_dict.get('processing_duration_seconds'):
                    duration = int(bot_dict['processing_duration_seconds'])
                    bot_dict['processing_duration_formatted'] = format_duration(duration)
                else:
                    bot_dict['processing_duration_seconds'] = None
                    bot_dict['processing_duration_formatted'] = None
                
                # Format time since last heartbeat
                if bot_dict.get('seconds_since_heartbeat'):
                    seconds = int(bot_dict['seconds_since_heartbeat'])
                    bot_dict['heartbeat_age_formatted'] = format_duration(seconds) + " ago"
                else:
                    bot_dict['heartbeat_age_formatted'] = None
                
                # Format time since deletion
                if bot_dict.get('seconds_since_deleted'):
                    seconds = int(bot_dict['seconds_since_deleted'])
                    bot_dict['deleted_age_formatted'] = format_duration(seconds) + " ago"
                else:
                    bot_dict['deleted_age_formatted'] = None
                
                result.append(bot_dict)
            
            return result
            
    except Exception as e:
        logger.error(f"Failed to get bots: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bots")

@app.delete("/bots/{bot_id}")
async def delete_bot(bot_id: str, token: str = Depends(verify_admin_token)):
    """Delete a bot and handle its current job"""
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Check if bot has current job
                bot = await conn.fetchrow("""
                    SELECT current_job_id FROM bots WHERE id = $1 AND deleted_at IS NULL
                """, bot_id)
                
                if not bot:
                    raise HTTPException(status_code=404, detail="Bot not found")
                
                bot_dict = dict(bot)
                
                # Handle current job if exists
                if bot_dict['current_job_id']:
                    job = await conn.fetchrow("""
                        SELECT status FROM jobs WHERE id = $1
                    """, bot_dict['current_job_id'])
                    
                    if job:
                        job_dict = dict(job)
                        if job_dict['status'] == 'processing':
                            # Mark job as failed due to bot termination
                            await conn.execute("""
                                UPDATE jobs 
                                SET status = 'failed', finished_at = NOW(), error = 'Bot terminated'
                                WHERE id = $1
                            """, bot_dict['current_job_id'])
                        elif job_dict['status'] == 'claimed':
                            # Return job to pending
                            await conn.execute("""
                                UPDATE jobs 
                                SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                                WHERE id = $1
                            """, bot_dict['current_job_id'])
                
                # Mark bot as deleted
                await conn.execute("""
                    UPDATE bots 
                    SET deleted_at = NOW(), current_job_id = NULL, status = 'down'
                    WHERE id = $1
                """, bot_id)
        
        logger.info(f"Bot deleted: {bot_id}")
        return {"status": "deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete bot")

@app.get("/bots/{bot_id}/stats")
async def get_bot_stats(bot_id: str, hours: int = 24):
    """Get comprehensive performance stats and history for a bot"""
    try:
        async with db_manager.get_connection() as conn:
            # Overall stats
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_jobs,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(MIN(duration_ms), 0) as min_duration_ms,
                    COALESCE(MAX(duration_ms), 0) as max_duration_ms,
                    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM results 
                WHERE processed_by = $1 
                AND processed_at > NOW() - make_interval(hours => $2)
            """, bot_id, hours)
            
            # Hourly performance for the last 24 hours (for graphing)
            hourly_stats = await conn.fetch("""
                SELECT 
                    DATE_TRUNC('hour', processed_at) as hour,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                FROM results 
                WHERE processed_by = $1 
                AND processed_at > NOW() - INTERVAL '24 hours'
                GROUP BY DATE_TRUNC('hour', processed_at)
                ORDER BY hour DESC
            """, bot_id)
            
            # Recent job history
            recent_jobs = await conn.fetch("""
                SELECT 
                    job_id,
                    status,
                    duration_ms,
                    processed_at,
                    error
                FROM results 
                WHERE processed_by = $1 
                ORDER BY processed_at DESC 
                LIMIT 50
            """, bot_id)
            
            if not stats or stats['total_jobs'] == 0:
                return {
                    "bot_id": bot_id,
                    "period_hours": hours,
                    "total_jobs": 0,
                    "avg_duration_ms": 0,
                    "min_duration_ms": 0,
                    "max_duration_ms": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "success_rate": 0.0,
                    "hourly_performance": [],
                    "recent_jobs": []
                }
            
            stats_dict = dict(stats)
            stats_dict["bot_id"] = bot_id
            stats_dict["period_hours"] = hours
            stats_dict["success_rate"] = (stats_dict["succeeded"] / stats_dict["total_jobs"]) * 100 if stats_dict["total_jobs"] > 0 else 0.0
            
            # Format hourly performance for charting
            stats_dict["hourly_performance"] = [
                {
                    "hour": row["hour"].isoformat(),
                    "total": row["total"],
                    "succeeded": row["succeeded"],
                    "failed": row["failed"],
                    "success_rate": (row["succeeded"] / row["total"]) * 100 if row["total"] > 0 else 0,
                    "avg_duration_ms": row["avg_duration_ms"]
                }
                for row in hourly_stats
            ]
            
            # Format recent jobs
            stats_dict["recent_jobs"] = [
                {
                    "job_id": row["job_id"],
                    "status": row["status"],
                    "duration_ms": row["duration_ms"],
                    "duration_formatted": format_duration(row["duration_ms"] // 1000) if row["duration_ms"] else None,
                    "processed_at": row["processed_at"].isoformat() if row["processed_at"] else None,
                    "error": row["error"]
                }
                for row in recent_jobs
            ]
            
            return stats_dict
            
    except Exception as e:
        logger.error(f"Failed to get stats for bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bot stats")

# Metrics endpoint
@app.get("/metrics/summary")
async def get_metrics_summary():
    """Get system metrics summary for dashboard"""
    try:
        async with db_manager.get_connection() as conn:
            # Job counts by status
            job_rows = await conn.fetch("""
                SELECT status, COUNT(*) as count 
                FROM jobs 
                GROUP BY status
            """)
            
            job_counts = {row['status']: row['count'] for row in job_rows}
            
            # Bot counts
            bot_row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN NOW() - INTERVAL '2 minutes' > last_heartbeat_at THEN 1 ELSE 0 END) as down,
                    SUM(CASE WHEN status = 'busy' AND NOW() - INTERVAL '2 minutes' <= last_heartbeat_at THEN 1 ELSE 0 END) as busy,
                    SUM(CASE WHEN status = 'idle' AND NOW() - INTERVAL '2 minutes' <= last_heartbeat_at THEN 1 ELSE 0 END) as idle
                FROM bots 
                WHERE deleted_at IS NULL
            """)
            
            bot_counts = dict(bot_row)
            
            # Recent throughput (last hour)
            throughput_row = await conn.fetchrow("""
                SELECT COUNT(*) as completed_last_hour
                FROM jobs 
                WHERE status IN ('succeeded', 'failed') 
                AND finished_at > NOW() - INTERVAL '1 hour'
            """)
            
            throughput = dict(throughput_row)
            
            return {
                "jobs": job_counts,
                "bots": bot_counts,
                "throughput": throughput
            }
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics")

# Datalake endpoints
@app.get("/datalake/stats")
async def get_datalake_stats(days: int = 7):
    """Get datalake statistics"""
    try:
        stats = await datalake.get_stats(days)
        return stats
    except Exception as e:
        logger.error(f"Failed to get datalake stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get datalake stats")

@app.get("/datalake/export/{date}")
async def export_datalake_date(date: str):
    """Export datalake data for a specific date"""
    try:
        date_obj = datetime.fromisoformat(date.replace('Z', '+00:00'))
        data = await datalake.export_date_as_json(date_obj)
        return data
    except Exception as e:
        logger.error(f"Failed to export datalake data for {date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to export data")

# Cleanup endpoints
@app.post("/admin/cleanup", dependencies=[Depends(verify_admin_token)])
async def trigger_cleanup(dry_run: bool = False):
    """Manually trigger cleanup of orphaned resources"""
    try:
        # Override dry_run setting temporarily
        original_dry_run = cleanup_service.config["dry_run"]
        cleanup_service.config["dry_run"] = dry_run
        
        results = await cleanup_scheduler.force_cleanup()
        
        # Restore original setting
        cleanup_service.config["dry_run"] = original_dry_run
        
        return results
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@app.get("/admin/cleanup/status")
async def get_cleanup_status():
    """Get cleanup service status and configuration"""
    return {
        "service_running": cleanup_service._running,
        "config": cleanup_service.config,
        "next_run": "Check logs for next scheduled run",
        "history": cleanup_service.get_history()
    }

@app.post("/admin/query", dependencies=[Depends(verify_admin_token)])
async def execute_query(query_data: dict):
    """Execute a read-only query on the database (admin only)"""
    query = query_data.get("query", "").strip().upper()
    
    # Security: Only allow SELECT queries
    if not query.startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    
    try:
        async with db_manager.get_connection() as conn:
            rows = await conn.fetch(query_data["query"])
            return {"results": [dict(row) for row in rows]}
    except Exception as e:
        logger.error(f"Query execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@app.post("/bots/{bot_id}/reset", dependencies=[Depends(verify_admin_token)])
async def reset_bot_state(bot_id: str):
    """Reset bot state to clear stale job assignments"""
    try:
        async with db_manager.get_connection() as conn:
            async with conn.transaction():
                # Clear any stale job assignment
                result = await conn.execute("""
                    UPDATE bots 
                    SET current_job_id = NULL, status = 'idle'
                    WHERE id = $1 AND current_job_id IS NOT NULL
                """, bot_id)
                
                # Return jobs to pending if they were claimed by this bot
                await conn.execute("""
                    UPDATE jobs 
                    SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                    WHERE claimed_by = $1 AND status = 'claimed'
                """, bot_id)
                
                logger.info(f"Reset bot state: {bot_id}")
                return {"status": "reset", "bot_id": bot_id}
                
    except Exception as e:
        logger.error(f"Failed to reset bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

# Automatic orphaned job recovery
async def recover_orphaned_jobs():
    """Recover jobs claimed by dead bots"""
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        
        async with db_manager.get_connection() as conn:
            # Find jobs claimed by bots that haven't sent heartbeat
            orphaned_jobs = await conn.fetch("""
                SELECT j.id, j.claimed_by 
                FROM jobs j
                JOIN bots b ON j.claimed_by = b.id
                WHERE j.status = 'claimed' 
                AND b.last_heartbeat_at < $1
                AND b.deleted_at IS NULL
            """, cutoff)
            
            if orphaned_jobs:
                async with conn.transaction():
                    for job in orphaned_jobs:
                        await conn.execute("""
                            UPDATE jobs 
                            SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                                attempts = attempts + 1
                            WHERE id = $1
                        """, job['id'])
                        
                        logger.info("Recovered orphaned job", job_id=job['id'], 
                                   bot_id=job['claimed_by'])
                
                logger.info(f"Recovered {len(orphaned_jobs)} orphaned jobs")
                
    except Exception as e:
        logger.error(f"Orphaned job recovery failed: {e}")

# Background task for job recovery
async def job_recovery_loop():
    """Background task to recover orphaned jobs"""
    while True:
        try:
            await recover_orphaned_jobs()
            await asyncio.sleep(60)  # Run every minute
        except Exception as e:
            logger.error(f"Job recovery loop error: {e}")
            await asyncio.sleep(60)

# Auto-populate jobs
async def auto_populate_jobs():
    """Background task to automatically populate jobs"""
    import random
    
    while True:
        try:
            await asyncio.sleep(config.POPULATE_INTERVAL_MS / 1000)  # Convert to seconds
            
            logger.info("Auto-populating jobs...")
            
            async with db_manager.get_connection() as conn:
                async with conn.transaction():
                    for i in range(config.BATCH_SIZE):
                        job_id = str(uuid.uuid4())
                        a = random.randint(0, 999)
                        b = random.randint(0, 999)
                        
                        await conn.execute("""
                            INSERT INTO jobs (id, a, b, status, created_at) 
                            VALUES ($1, $2, $3, 'pending', CURRENT_TIMESTAMP)
                        """, job_id, a, b)
            
            logger.info(f"Auto-created {config.BATCH_SIZE} jobs")
            
        except Exception as e:
            logger.error(f"Failed to auto-populate jobs: {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize database and start background tasks"""
    await db_manager.initialize()
    asyncio.create_task(auto_populate_jobs())
    asyncio.create_task(job_recovery_loop())
    await cleanup_scheduler.start()
    logger.info("Application started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources"""
    await cleanup_scheduler.stop()
    await db_manager.close()
    logger.info("Application shutdown completed")

if __name__ == "__main__":
    import os
    import random
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 3001)),
        reload=True
    )