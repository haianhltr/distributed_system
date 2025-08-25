"""Administrative operations business logic."""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import structlog

from main_server.database import DatabaseManager
from main_server.repositories import create_unit_of_work
from main_server.cleanup_service import CleanupScheduler
from main_server.models.schemas import QueryRequest
from main_server.core.exceptions import ValidationError, BusinessRuleViolation


logger = structlog.get_logger(__name__)


class AdminService:
    """Service for administrative operations."""
    
    def __init__(self, db_manager: DatabaseManager, cleanup_scheduler: Optional[CleanupScheduler] = None):
        self.db = db_manager
        self.cleanup_scheduler = cleanup_scheduler
        
    async def execute_query(self, query_data: QueryRequest) -> Dict[str, Any]:
        """Execute a read-only query on the database (admin only)."""
        query = query_data.query.strip()
        
        # Security: Only allow SELECT queries
        if not query.upper().startswith("SELECT"):
            raise BusinessRuleViolation("Only SELECT queries are allowed")
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                rows = await uow.execute_query(query_data.query)
                return {"results": rows}
        except Exception as e:
            logger.error("Query execution failed", error=str(e))
            raise ValidationError(f"Query failed: {str(e)}")
    
    async def trigger_cleanup(self, dry_run: bool = False) -> Dict[str, Any]:
        """Manually trigger cleanup of orphaned resources."""
        try:
            if not self.cleanup_scheduler:
                raise ValidationError("Cleanup scheduler not available")
                
            # Get the cleanup service from scheduler
            cleanup_service = self.cleanup_scheduler.cleanup_service
            
            # Override dry_run setting temporarily
            original_dry_run = cleanup_service.config.get("dry_run", False)
            cleanup_service.config["dry_run"] = dry_run
            
            results = await self.cleanup_scheduler.force_cleanup()
            
            # Restore original setting
            cleanup_service.config["dry_run"] = original_dry_run
            
            return results
        except Exception as e:
            logger.error("Cleanup failed", error=str(e))
            raise ValidationError(f"Cleanup failed: {str(e)}")
    
    async def get_cleanup_status(self) -> Dict[str, Any]:
        """Get cleanup service status and configuration."""
        if not self.cleanup_scheduler:
            return {
                "service_running": False,
                "config": {},
                "next_run": "N/A",
                "history": []
            }
            
        cleanup_service = self.cleanup_scheduler.cleanup_service
        return {
            "service_running": cleanup_service._running,
            "config": cleanup_service.config,
            "next_run": "Check logs for next scheduled run",
            "history": cleanup_service.get_history()
        }
    
    async def get_stuck_jobs(self) -> Dict[str, Any]:
        """Get summary of potentially stuck jobs."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Get stuck processing jobs (>10 minutes)
                stuck_processing = await uow.jobs.find_stuck_jobs(minutes=10)
                
                # Get stuck claimed jobs (>5 minutes)
                stuck_claimed_query = """
                    SELECT j.id, j.status, j.claimed_by,
                           EXTRACT(EPOCH FROM (NOW() - j.claimed_at)) / 60 as claimed_minutes
                    FROM jobs j
                    WHERE j.status = 'claimed'
                    AND j.claimed_at < NOW() - INTERVAL '5 minutes'
                    ORDER BY j.claimed_at ASC
                    LIMIT 20
                """
                stuck_claimed = await uow.execute_query(stuck_claimed_query)
                
                # Get bots marked as potentially stuck
                stuck_bots_query = """
                    SELECT id, current_job_id, stuck_job_id
                    FROM bots
                    WHERE health_status = 'potentially_stuck'
                    ORDER BY health_checked_at DESC NULLS LAST
                    LIMIT 20
                """
                stuck_bots = await uow.execute_query(stuck_bots_query)
                
                return {
                    "stuck_processing_jobs": stuck_processing[:20],  # Ensure limit
                    "stuck_claimed_jobs": stuck_claimed,
                    "potentially_stuck_bots": stuck_bots,
                    "summary": {
                        "processing_count": len(stuck_processing),
                        "claimed_count": len(stuck_claimed),
                        "stuck_bots_count": len(stuck_bots)
                    }
                }
                
        except Exception as e:
            logger.error(f"Failed to get stuck jobs: {e}")
            raise ValidationError(f"Failed to get stuck jobs: {str(e)}")
    
    async def cleanup_inconsistent_states(self) -> Dict[str, Any]:
        """Clean up inconsistent bot-job states."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Find bots with inconsistent states
                query = """
                    SELECT b.id, b.current_job_id, j.id as claimed_job_id, j.status as job_status
                    FROM bots b
                    LEFT JOIN jobs j ON j.claimed_by = b.id AND j.status IN ('claimed', 'processing')
                    WHERE (b.current_job_id IS NULL AND j.id IS NOT NULL)
                       OR (b.current_job_id IS NOT NULL AND j.id IS NULL)
                       OR (b.current_job_id != j.id AND j.id IS NOT NULL)
                """
                inconsistent_bots = await uow.execute_query(query)
                
                fixed_count = 0
                for bot in inconsistent_bots:
                    bot_id = bot['id']
                    bot_job_id = bot['current_job_id']
                    claimed_job_id = bot['claimed_job_id']
                    job_status = bot['job_status']
                    
                    if claimed_job_id and (bot_job_id != claimed_job_id or bot_job_id is None):
                        # Fix inconsistent job assignment
                        if job_status in ['claimed', 'processing']:
                            # Release the job
                            await uow.jobs.release_to_pending(claimed_job_id)
                            
                            # Add error message
                            await uow.execute_command("""
                                UPDATE jobs 
                                SET error = CASE 
                                    WHEN error IS NULL THEN 'Auto-cleanup: inconsistent state'
                                    ELSE error || ' | Auto-cleanup: inconsistent state'
                                END
                                WHERE id = $1
                            """, claimed_job_id)
                        
                        # Reset bot state
                        await uow.bots.set_current_job(bot_id, None, 'idle')
                        
                        fixed_count += 1
                        logger.info(f"Fixed inconsistent state for bot {bot_id}: job {claimed_job_id} reset to pending")
                
                return {
                    "status": "cleanup_completed",
                    "bots_fixed": fixed_count,
                    "message": f"Fixed {fixed_count} inconsistent bot-job states"
                }
                
        except Exception as e:
            logger.error(f"Failed to cleanup inconsistent states: {e}")
            raise ValidationError(f"Cleanup failed: {str(e)}")