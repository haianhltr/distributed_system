"""Metrics and monitoring business logic."""

from datetime import datetime
from typing import Dict, Any
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from core.exceptions import ValidationError


logger = structlog.get_logger(__name__)


class MetricsService:
    """Service for metrics and monitoring operations."""
    
    def __init__(self, db_manager: DatabaseManager, datalake_manager: DatalakeManager):
        self.db = db_manager
        self.datalake = datalake_manager
        
    async def get_simple_metrics(self) -> Dict[str, Any]:
        """Simple JSON metrics endpoint."""
        try:
            async with self.db.get_connection() as conn:
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
            logger.error("Failed to get metrics", error=str(e))
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": "Failed to retrieve metrics",
                "jobs": {"total": 0, "by_status": {}},
                "bots": {"total": 0, "by_status": {}},
                "activity": {"jobs_created_last_hour": 0}
            }
    
    async def get_metrics_summary(self) -> Dict[str, Any]:
        """Get system metrics summary for dashboard."""
        try:
            async with self.db.get_connection() as conn:
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
            logger.error("Failed to get metrics summary", error=str(e))
            raise ValidationError(f"Failed to retrieve metrics: {str(e)}")
    
    async def get_datalake_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get datalake statistics."""
        try:
            return await self.datalake.get_stats(days)
        except Exception as e:
            logger.error("Failed to get datalake stats", error=str(e))
            raise ValidationError(f"Failed to get datalake stats: {str(e)}")
    
    async def export_datalake_date(self, date_str: str) -> Dict[str, Any]:
        """Export datalake data for a specific date."""
        try:
            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            data = await self.datalake.export_date_as_json(date_obj)
            return data
        except Exception as e:
            logger.error("Failed to export datalake data", date=date_str, error=str(e))
            raise ValidationError(f"Failed to export data: {str(e)}")