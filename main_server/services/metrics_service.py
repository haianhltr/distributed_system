"""Metrics and monitoring business logic."""

from datetime import datetime
from typing import Dict, Any
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from repositories import create_unit_of_work
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
            async with create_unit_of_work(self.db.pool) as uow:
                # Get job metrics
                job_metrics = await uow.jobs.get_metrics()
                
                # Get bot metrics
                bot_metrics = await uow.bots.get_metrics()
                
                # Get throughput
                throughput = await uow.results.get_system_throughput(hours=1)
                
                # Get job creation count
                jobs_created_query = """
                    SELECT COUNT(*) FROM jobs 
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                jobs_created_result = await uow.execute_query(jobs_created_query)
                jobs_created = jobs_created_result[0]['count'] if jobs_created_result else 0
                
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "jobs": {
                        "total": sum(job_metrics.values()),
                        "by_status": job_metrics
                    },
                    "bots": bot_metrics,
                    "activity": {
                        "jobs_created_last_hour": jobs_created,
                        "jobs_completed_last_hour": throughput
                    }
                }
                
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
            async with create_unit_of_work(self.db.pool) as uow:
                # Job counts by status
                job_metrics = await uow.jobs.get_metrics()
                
                # Bot counts
                bot_metrics = await uow.bots.get_metrics()
                
                # Recent throughput
                completed_last_hour = await uow.results.get_system_throughput(hours=1)
                
                # Operation statistics
                operation_stats = await uow.results.get_operation_stats()
                
                return {
                    "jobs": job_metrics,
                    "bots": bot_metrics,
                    "throughput": {
                        "completed_last_hour": completed_last_hour
                    },
                    "operations": operation_stats
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