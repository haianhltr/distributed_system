"""Repository for job-related database operations."""

from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from .base import BaseRepository


class JobRepository(BaseRepository):
    """Repository for managing jobs in the database."""
    
    @property
    def table_name(self) -> str:
        return "jobs"
    
    async def create(self, a: int, b: int, operation: str = "sum") -> Dict[str, Any]:
        """Create a new job."""
        job_id = str(uuid.uuid4())
        query = """
            INSERT INTO jobs (id, a, b, operation, status, created_at) 
            VALUES ($1, $2, $3, $4, 'pending', CURRENT_TIMESTAMP)
            RETURNING *
        """
        row = await self.connection.fetchrow(query, job_id, a, b, operation)
        return dict(row)
    
    async def create_batch(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create multiple jobs in a batch."""
        created_jobs = []
        for job_data in jobs:
            job_id = str(uuid.uuid4())
            query = """
                INSERT INTO jobs (id, a, b, operation, status, created_at) 
                VALUES ($1, $2, $3, $4, 'pending', CURRENT_TIMESTAMP)
                RETURNING *
            """
            row = await self.connection.fetchrow(
                query, 
                job_id, 
                job_data['a'], 
                job_data['b'], 
                job_data.get('operation', 'sum')
            )
            created_jobs.append(dict(row))
        return created_jobs
    
    async def find_by_status(
        self, 
        status: str, 
        limit: int = 100, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Find jobs by status."""
        query = """
            SELECT * FROM jobs 
            WHERE status = $1 
            ORDER BY created_at DESC 
            LIMIT $2 OFFSET $3
        """
        rows = await self.connection.fetch(query, status, limit, offset)
        return [dict(row) for row in rows]
    
    async def find_pending_for_operation(
        self, 
        operation: str, 
        limit: int = 1
    ) -> Optional[Dict[str, Any]]:
        """Find pending jobs for a specific operation."""
        query = """
            SELECT * FROM jobs 
            WHERE status = 'pending' AND operation = $1
            ORDER BY created_at ASC 
            LIMIT $2
        """
        rows = await self.connection.fetch(query, operation, limit)
        return dict(rows[0]) if rows else None
    
    async def claim(self, job_id: str, bot_id: str) -> bool:
        """Atomically claim a job for a bot."""
        query = """
            UPDATE jobs 
            SET status = 'claimed', 
                claimed_by = $1, 
                claimed_at = NOW()
            WHERE id = $2 AND status = 'pending'
        """
        result = await self.connection.execute(query, bot_id, job_id)
        return result.split()[-1] != "0"
    
    async def start(self, job_id: str, bot_id: str) -> bool:
        """Mark a job as started."""
        query = """
            UPDATE jobs 
            SET status = 'processing', 
                started_at = NOW()
            WHERE id = $1 AND claimed_by = $2 AND status = 'claimed'
        """
        result = await self.connection.execute(query, job_id, bot_id)
        return result.split()[-1] != "0"
    
    async def complete(self, job_id: str, bot_id: str) -> bool:
        """Mark a job as completed."""
        query = """
            UPDATE jobs 
            SET status = 'succeeded', 
                finished_at = NOW()
            WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
        """
        result = await self.connection.execute(query, job_id, bot_id)
        return result.split()[-1] != "0"
    
    async def fail(self, job_id: str, bot_id: str, error: str) -> bool:
        """Mark a job as failed."""
        query = """
            UPDATE jobs 
            SET status = 'failed', 
                finished_at = NOW(), 
                attempts = attempts + 1, 
                error = $3
            WHERE id = $1 AND claimed_by = $2 AND status = 'processing'
        """
        result = await self.connection.execute(query, job_id, bot_id, error)
        return result.split()[-1] != "0"
    
    async def release_to_pending(self, job_id: str) -> bool:
        """Release a job back to pending status."""
        query = """
            UPDATE jobs 
            SET status = 'pending', 
                claimed_by = NULL, 
                claimed_at = NULL,
                started_at = NULL
            WHERE id = $1 AND status IN ('claimed', 'processing')
        """
        result = await self.connection.execute(query, job_id)
        return result.split()[-1] != "0"
    
    async def find_stuck_jobs(self, minutes: int = 10) -> List[Dict[str, Any]]:
        """Find jobs that have been processing for too long."""
        query = """
            SELECT j.*, 
                   EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 as processing_minutes
            FROM jobs j
            WHERE j.status = 'processing'
            AND j.started_at < NOW() - INTERVAL '%s minutes'
            ORDER BY j.started_at ASC
        """
        rows = await self.connection.fetch(query % minutes)
        return [dict(row) for row in rows]
    
    async def find_orphaned_jobs(self, heartbeat_cutoff: datetime) -> List[Dict[str, Any]]:
        """Find jobs claimed by bots that haven't sent heartbeat."""
        query = """
            SELECT j.id, j.claimed_by 
            FROM jobs j
            JOIN bots b ON j.claimed_by = b.id
            WHERE j.status = 'claimed' 
            AND b.last_heartbeat_at < $1
            AND b.deleted_at IS NULL
        """
        rows = await self.connection.fetch(query, heartbeat_cutoff)
        return [dict(row) for row in rows]
    
    async def get_metrics(self) -> Dict[str, int]:
        """Get job metrics by status."""
        query = """
            SELECT status, COUNT(*) as count 
            FROM jobs 
            GROUP BY status
        """
        rows = await self.connection.fetch(query)
        return {row['status']: row['count'] for row in rows}