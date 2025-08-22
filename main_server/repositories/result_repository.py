"""Repository for result-related database operations."""

from typing import List, Dict, Any
from datetime import datetime
import uuid

from .base import BaseRepository


class ResultRepository(BaseRepository):
    """Repository for managing job results in the database."""
    
    @property
    def table_name(self) -> str:
        return "results"
    
    async def create(
        self,
        job_id: str,
        a: int,
        b: int,
        operation: str,
        result: int,
        processed_by: str,
        duration_ms: int,
        status: str = "succeeded",
        error: str = None
    ) -> Dict[str, Any]:
        """Create a new result record."""
        result_id = str(uuid.uuid4())
        query = """
            INSERT INTO results (
                id, job_id, a, b, operation, result, 
                processed_by, processed_at, duration_ms, status, error
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9, $10)
            RETURNING *
        """
        row = await self.connection.fetchrow(
            query, result_id, job_id, a, b, operation, 
            result, processed_by, duration_ms, status, error
        )
        return dict(row)
    
    async def find_by_bot(
        self, 
        bot_id: str, 
        hours: int = 24,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Find results processed by a specific bot."""
        query = """
            SELECT 
                job_id,
                status,
                duration_ms,
                processed_at,
                error
            FROM results 
            WHERE processed_by = $1 
            AND processed_at > NOW() - make_interval(hours => $2)
            ORDER BY processed_at DESC 
            LIMIT $3
        """
        rows = await self.connection.fetch(query, bot_id, hours, limit)
        return [dict(row) for row in rows]
    
    async def get_bot_stats(self, bot_id: str, hours: int = 24) -> Dict[str, Any]:
        """Get performance statistics for a bot."""
        query = """
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
        """
        row = await self.connection.fetchrow(query, bot_id, hours)
        return dict(row) if row else {
            "total_jobs": 0,
            "avg_duration_ms": 0,
            "min_duration_ms": 0,
            "max_duration_ms": 0,
            "succeeded": 0,
            "failed": 0
        }
    
    async def get_hourly_stats(self, bot_id: str) -> List[Dict[str, Any]]:
        """Get hourly performance statistics for a bot."""
        query = """
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
        """
        rows = await self.connection.fetch(query, bot_id)
        return [dict(row) for row in rows]
    
    async def get_system_throughput(self, hours: int = 1) -> int:
        """Get system throughput for the specified hours."""
        query = """
            SELECT COUNT(*) as completed_count
            FROM results 
            WHERE processed_at > NOW() - make_interval(hours => $1)
        """
        count = await self.connection.fetchval(query, hours)
        return count or 0
    
    async def get_operation_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics grouped by operation type."""
        query = """
            SELECT 
                operation,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                COALESCE(AVG(duration_ms), 0)::int as avg_duration_ms
            FROM results
            WHERE processed_at > NOW() - INTERVAL '24 hours'
            GROUP BY operation
        """
        rows = await self.connection.fetch(query)
        return {
            row['operation']: {
                'total': row['total'],
                'succeeded': row['succeeded'],
                'failed': row['failed'],
                'avg_duration_ms': row['avg_duration_ms']
            }
            for row in rows
        }