"""Bot management business logic."""

from datetime import datetime
from typing import List, Dict, Any
import structlog

from database import DatabaseManager
from models.schemas import BotRegister, BotHeartbeat
from core.exceptions import NotFoundError, ValidationError


logger = structlog.get_logger(__name__)


def format_duration(seconds):
    """Format duration in seconds to human readable format."""
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


class BotService:
    """Service for bot management operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
    async def register_bot(self, bot_data: BotRegister) -> Dict[str, str]:
        """Register a new bot."""
        bot_id = bot_data.bot_id
        
        try:
            async with self.db.get_connection() as conn:
                await conn.execute("""
                    INSERT INTO bots (id, status, last_heartbeat_at, created_at)
                    VALUES ($1, 'idle', NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        status = 'idle',
                        last_heartbeat_at = NOW(),
                        deleted_at = NULL
                """, bot_id)
            
            logger.info("Bot registered", bot_id=bot_id)
            return {"status": "registered", "bot_id": bot_id}
            
        except Exception as e:
            logger.error("Failed to register bot", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Registration failed: {str(e)}")
    
    async def update_heartbeat(self, heartbeat_data: BotHeartbeat) -> Dict[str, str]:
        """Update bot heartbeat."""
        bot_id = heartbeat_data.bot_id
        
        try:
            async with self.db.get_connection() as conn:
                result = await conn.execute("""
                    UPDATE bots 
                    SET last_heartbeat_at = NOW()
                    WHERE id = $1 AND deleted_at IS NULL
                """, bot_id)
                
                if result == 'UPDATE 0':
                    raise NotFoundError("Bot not found or deleted")
                
                return {"status": "ok"}
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to update heartbeat", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to update heartbeat: {str(e)}")
    
    async def get_bots(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all bots with job processing duration and lifecycle status."""
        try:
            async with self.db.get_connection() as conn:
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
            logger.error("Failed to get bots", error=str(e))
            raise ValidationError(f"Failed to retrieve bots: {str(e)}")
    
    async def delete_bot(self, bot_id: str) -> Dict[str, str]:
        """Delete a bot and handle its current job."""
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Check if bot has current job
                    bot = await conn.fetchrow("""
                        SELECT current_job_id FROM bots WHERE id = $1 AND deleted_at IS NULL
                    """, bot_id)
                    
                    if not bot:
                        raise NotFoundError("Bot not found")
                    
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
            
            logger.info("Bot deleted", bot_id=bot_id)
            return {"status": "deleted"}
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to delete bot", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to delete bot: {str(e)}")
    
    async def get_bot_stats(self, bot_id: str, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive performance stats and history for a bot."""
        try:
            async with self.db.get_connection() as conn:
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
                    AND processed_at > NOW() - INTERVAL $2
                """, bot_id, f"{hours} hours")
                
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
            logger.error("Failed to get bot stats", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to retrieve bot stats: {str(e)}")
    
    async def reset_bot_state(self, bot_id: str) -> Dict[str, str]:
        """Reset bot state to clear stale job assignments."""
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Clear any stale job assignment
                    await conn.execute("""
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
                    
                    logger.info("Reset bot state", bot_id=bot_id)
                    return {"status": "reset", "bot_id": bot_id}
                    
        except Exception as e:
            logger.error("Failed to reset bot", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Reset failed: {str(e)}")
    
    async def cleanup_dead_bots(self) -> Dict[str, Any]:
        """Remove bots that have been down for more than 10 minutes."""
        try:
            async with self.db.get_connection() as conn:
                result = await conn.execute("""
                    UPDATE bots 
                    SET deleted_at = NOW() 
                    WHERE last_heartbeat_at < NOW() - INTERVAL '10 minutes'
                    AND deleted_at IS NULL
                """)
                
                count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
                logger.info("Cleaned up dead bots", count=count)
                return {"cleaned_up": count, "status": "success"}
                
        except Exception as e:
            logger.error("Failed to cleanup dead bots", error=str(e))
            raise ValidationError(f"Failed to cleanup bots: {str(e)}")
    
    async def reset_all_bot_states(self) -> Dict[str, Any]:
        """Reset all bots to idle state and handle their orphaned jobs."""
        try:
            async with self.db.get_connection() as conn:
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
                                logger.info("Reset job to pending", job_id=job_id)
                        
                        # Clear bot's current job and set to idle
                        await conn.execute("""
                            UPDATE bots 
                            SET current_job_id = NULL, status = 'idle'
                            WHERE id = $1
                        """, bot_id)
                        
                        reset_count += 1
                        logger.info("Reset bot to idle", bot_id=bot_id)
                    
                    return {"reset_bots": reset_count, "status": "success"}
                    
        except Exception as e:
            logger.error("Failed to reset bot states", error=str(e))
            raise ValidationError(f"Failed to reset bot states: {str(e)}")