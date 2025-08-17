"""Service for manual job release operations."""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import structlog

from database import DatabaseManager
# Simple exceptions to avoid import issues
class NotFoundError(Exception):
    pass

class ValidationError(Exception):
    pass

logger = structlog.get_logger(__name__)


class JobReleaseService:
    """Handle manual job release operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    async def release_job_from_bot(self, job_id: str, admin_user: Optional[str] = None) -> Dict[str, Any]:
        """Release a stuck job back to pending state.
        
        This allows manual intervention when a job is stuck processing.
        The job is reset to pending state and the bot is freed up.
        """
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Get job and bot info
                    job_info = await conn.fetchrow("""
                        SELECT j.*, b.id as bot_id, b.status as bot_status,
                               EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 as processing_minutes
                        FROM jobs j
                        LEFT JOIN bots b ON j.claimed_by = b.id
                        WHERE j.id = $1
                    """, job_id)
                    
                    if not job_info:
                        raise NotFoundError(f"Job {job_id} not found")
                    
                    job_dict = dict(job_info)
                    bot_id = job_dict.get('bot_id')
                    
                    # Validate job is in a releasable state
                    if job_dict['status'] not in ['claimed', 'processing']:
                        raise ValidationError(
                            f"Job {job_id} is in {job_dict['status']} state and cannot be released"
                        )
                    
                    # Reset job to pending
                    await conn.execute("""
                        UPDATE jobs 
                        SET status = 'pending', 
                            claimed_by = NULL, 
                            claimed_at = NULL,
                            started_at = NULL,
                            error = CASE 
                                WHEN error IS NULL THEN 'Manually released from stuck state'
                                ELSE error || ' | Manually released from stuck state'
                            END
                        WHERE id = $1
                    """, job_id)
                    
                    # Reset bot state if it exists
                    if bot_id:
                        await conn.execute("""
                            UPDATE bots 
                            SET current_job_id = NULL, 
                                status = 'idle',
                                health_status = 'normal',
                                stuck_job_id = NULL
                            WHERE id = $1
                        """, bot_id)
                    
                    # Log the manual intervention
                    await self._log_manual_release(conn, job_id, bot_id, admin_user)
                    
                    logger.info(
                        "Manually released stuck job",
                        job_id=job_id,
                        bot_id=bot_id,
                        previous_status=job_dict['status'],
                        processing_minutes=job_dict.get('processing_minutes', 0),
                        admin_user=admin_user
                    )
                    
                    return {
                        "status": "released",
                        "job_id": job_id,
                        "bot_id": bot_id,
                        "previous_status": job_dict['status'],
                        "action": "manual_release",
                        "message": f"Job {job_id} has been released back to pending state"
                    }
                    
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error("Failed to release job", job_id=job_id, error=str(e))
            raise ValidationError(f"Failed to release job: {str(e)}")
    
    async def restart_bot(self, bot_id: str, admin_user: Optional[str] = None) -> Dict[str, Any]:
        """Mark a bot for restart by setting it to 'down' status.
        
        This will cause the bot to be cleaned up and potentially restarted
        by the orchestration system.
        """
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Get bot info
                    bot_info = await conn.fetchrow("""
                        SELECT * FROM bots WHERE id = $1
                    """, bot_id)
                    
                    if not bot_info:
                        raise NotFoundError(f"Bot {bot_id} not found")
                    
                    bot_dict = dict(bot_info)
                    
                    # Mark bot as down
                    await conn.execute("""
                        UPDATE bots 
                        SET status = 'down',
                            health_status = 'normal',
                            stuck_job_id = NULL
                        WHERE id = $1
                    """, bot_id)
                    
                    # If bot had a job, release it
                    if bot_dict['current_job_id']:
                        await conn.execute("""
                            UPDATE jobs 
                            SET status = 'pending', 
                                claimed_by = NULL, 
                                claimed_at = NULL,
                                started_at = NULL,
                                error = 'Bot restarted - job released'
                            WHERE id = $1 AND claimed_by = $2
                        """, bot_dict['current_job_id'], bot_id)
                    
                    logger.info(
                        "Manually restarted bot",
                        bot_id=bot_id,
                        previous_status=bot_dict['status'],
                        had_job=bot_dict['current_job_id'] is not None,
                        admin_user=admin_user
                    )
                    
                    return {
                        "status": "restarted",
                        "bot_id": bot_id,
                        "previous_status": bot_dict['status'],
                        "released_job_id": bot_dict['current_job_id'],
                        "action": "manual_restart",
                        "message": f"Bot {bot_id} has been marked for restart"
                    }
                    
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to restart bot", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to restart bot: {str(e)}")
    
    async def _log_manual_release(self, conn, job_id: str, bot_id: Optional[str], admin_user: Optional[str]):
        """Log manual intervention for audit purposes."""
        # In a real system, this would write to an audit log table
        # For now, we just log it
        logger.info(
            "AUDIT: Manual job release",
            job_id=job_id,
            bot_id=bot_id,
            admin_user=admin_user or "unknown",
            timestamp=datetime.utcnow().isoformat()
        )
    
    async def get_stuck_jobs_summary(self) -> Dict[str, Any]:
        """Get a summary of potentially stuck jobs for monitoring."""
        try:
            async with self.db.get_connection() as conn:
                # Get stuck processing jobs
                stuck_processing = await conn.fetch("""
                    SELECT j.id, j.status, j.claimed_by,
                           EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 as processing_minutes,
                           b.health_status
                    FROM jobs j
                    LEFT JOIN bots b ON j.claimed_by = b.id
                    WHERE j.status = 'processing'
                    AND j.started_at < NOW() - INTERVAL '10 minutes'
                    ORDER BY j.started_at ASC
                    LIMIT 20
                """)
                
                # Get stuck claimed jobs
                stuck_claimed = await conn.fetch("""
                    SELECT j.id, j.status, j.claimed_by,
                           EXTRACT(EPOCH FROM (NOW() - j.claimed_at)) / 60 as claimed_minutes
                    FROM jobs j
                    WHERE j.status = 'claimed'
                    AND j.claimed_at < NOW() - INTERVAL '5 minutes'
                    ORDER BY j.claimed_at ASC
                    LIMIT 20
                """)
                
                # Get bots marked as potentially stuck
                stuck_bots = await conn.fetch("""
                    SELECT id, current_job_id, stuck_job_id,
                           EXTRACT(EPOCH FROM (NOW() - health_checked_at)) / 60 as health_check_age_minutes
                    FROM bots
                    WHERE health_status = 'potentially_stuck'
                    ORDER BY health_checked_at DESC
                    LIMIT 20
                """)
                
                return {
                    "stuck_processing_jobs": [dict(job) for job in stuck_processing],
                    "stuck_claimed_jobs": [dict(job) for job in stuck_claimed],
                    "potentially_stuck_bots": [dict(bot) for bot in stuck_bots],
                    "summary": {
                        "processing_count": len(stuck_processing),
                        "claimed_count": len(stuck_claimed),
                        "stuck_bots_count": len(stuck_bots)
                    }
                }
                
        except Exception as e:
            logger.error("Failed to get stuck jobs summary", error=str(e))
            raise ValidationError(f"Failed to get stuck jobs summary: {str(e)}")