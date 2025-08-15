"""Administrative operations business logic."""

from datetime import datetime, timedelta
from typing import Dict, Any
import structlog

from database import DatabaseManager
from cleanup_service import CleanupScheduler
from models.schemas import QueryRequest
from core.exceptions import ValidationError, AuthenticationError


logger = structlog.get_logger(__name__)


class AdminService:
    """Service for administrative operations."""
    
    def __init__(self, db_manager: DatabaseManager, cleanup_scheduler: CleanupScheduler):
        self.db = db_manager
        self.cleanup_scheduler = cleanup_scheduler
        
    async def execute_query(self, query_data: QueryRequest) -> Dict[str, Any]:
        """Execute a read-only query on the database (admin only)."""
        query = query_data.query.strip().upper()
        
        # Security: Only allow SELECT queries
        if not query.startswith("SELECT"):
            raise ValidationError("Only SELECT queries are allowed")
        
        try:
            async with self.db.get_connection() as conn:
                rows = await conn.fetch(query_data.query)
                return {"results": [dict(row) for row in rows]}
        except Exception as e:
            logger.error("Query execution failed", error=str(e))
            raise ValidationError(f"Query failed: {str(e)}")
    
    async def trigger_cleanup(self, dry_run: bool = False) -> Dict[str, Any]:
        """Manually trigger cleanup of orphaned resources."""
        try:
            # Get the cleanup service from scheduler
            cleanup_service = self.cleanup_scheduler.cleanup_service
            
            # Override dry_run setting temporarily
            original_dry_run = cleanup_service.config["dry_run"]
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
        cleanup_service = self.cleanup_scheduler.cleanup_service
        return {
            "service_running": cleanup_service._running,
            "config": cleanup_service.config,
            "next_run": "Check logs for next scheduled run",
            "history": cleanup_service.get_history()
        }
    
    async def recover_orphaned_jobs(self) -> Dict[str, Any]:
        """Recover jobs claimed by dead bots."""
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=5)
            recovered_count = 0
            
            async with self.db.get_connection() as conn:
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
                            recovered_count += 1
                    
                    logger.info("Recovered orphaned jobs", count=recovered_count)
                
            return {
                "recovered_jobs": recovered_count,
                "status": "success",
                "timestamp": datetime.utcnow().isoformat()
            }
                
        except Exception as e:
            logger.error("Orphaned job recovery failed", error=str(e))
            raise ValidationError(f"Orphaned job recovery failed: {str(e)}")
    
    def verify_admin_token(self, token: str, admin_token: str) -> bool:
        """Verify admin authentication token."""
        if token != admin_token:
            raise AuthenticationError("Invalid authentication credentials")
        return True