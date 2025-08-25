"""Repository for bot-related database operations."""

from typing import Optional, List, Dict, Any
from datetime import datetime

from .base import BaseRepository


class BotRepository(BaseRepository):
    """Repository for managing bots in the database."""
    
    @property
    def table_name(self) -> str:
        return "bots"
    
    async def register(self, bot_key: str, bot_id: str) -> Dict[str, Any]:
        """Register a new bot or reactivate existing one."""
        query = """
            INSERT INTO bots (id, bot_key, status, last_heartbeat_at, created_at)
            VALUES ($1, $2, 'idle', NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                status = 'idle',
                last_heartbeat_at = NOW(),
                deleted_at = NULL
            RETURNING *
        """
        row = await self.connection.fetchrow(query, bot_id, bot_key)
        return dict(row)
    
    async def find_by_bot_key(self, bot_key: str) -> Optional[Dict[str, Any]]:
        """Find a bot by its bot_key."""
        query = """
            SELECT * FROM bots 
            WHERE bot_key = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = await self.connection.fetchrow(query, bot_key)
        return dict(row) if row else None
    
    async def update_heartbeat(self, bot_id: str) -> bool:
        """Update bot's last heartbeat timestamp."""
        query = """
            UPDATE bots 
            SET last_heartbeat_at = NOW()
            WHERE id = $1 AND deleted_at IS NULL
        """
        result = await self.connection.execute(query, bot_id)
        return result.split()[-1] != "0"
    
    async def assign_operation(self, bot_id: str, operation: str) -> bool:
        """Assign an operation type to a bot."""
        query = """
            UPDATE bots 
            SET assigned_operation = $2
            WHERE id = $1
        """
        result = await self.connection.execute(query, bot_id, operation)
        return result.split()[-1] != "0"
    
    async def set_current_job(self, bot_id: str, job_id: Optional[str], status: str = 'busy') -> bool:
        """Update bot's current job and status."""
        query = """
            UPDATE bots 
            SET current_job_id = $2, status = $3
            WHERE id = $1
        """
        result = await self.connection.execute(query, bot_id, job_id, status)
        return result.split()[-1] != "0"
    
    async def find_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Find all bots with a specific status."""
        query = """
            SELECT * FROM bots 
            WHERE status = $1 AND deleted_at IS NULL
            ORDER BY last_heartbeat_at DESC
        """
        rows = await self.connection.fetch(query, status)
        return [dict(row) for row in rows]
    
    async def find_active(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Find all active bots with computed status."""
        where_clause = "" if include_deleted else "WHERE b.deleted_at IS NULL"
        query = f"""
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
        """
        rows = await self.connection.fetch(query)
        return [dict(row) for row in rows]
    
    async def find_dead_bots(self, minutes: int = 10) -> List[Dict[str, Any]]:
        """Find bots that haven't sent heartbeat in specified minutes."""
        query = """
            SELECT * FROM bots 
            WHERE last_heartbeat_at < NOW() - INTERVAL '%s minutes'
            AND deleted_at IS NULL
        """
        rows = await self.connection.fetch(query % minutes)
        return [dict(row) for row in rows]
    
    async def soft_delete(self, bot_id: str) -> bool:
        """Soft delete a bot."""
        query = """
            UPDATE bots 
            SET deleted_at = NOW(), 
                current_job_id = NULL, 
                status = 'down'
            WHERE id = $1
        """
        result = await self.connection.execute(query, bot_id)
        return result.split()[-1] != "0"
    
    async def cleanup_dead_bots(self, minutes: int = 10) -> int:
        """Mark dead bots as deleted."""
        query = """
            UPDATE bots 
            SET deleted_at = NOW() 
            WHERE last_heartbeat_at < NOW() - INTERVAL '%s minutes'
            AND deleted_at IS NULL
        """
        result = await self.connection.execute(query % minutes)
        return int(result.split()[-1]) if result.startswith("UPDATE") else 0
    
    async def reset_bot_state(self, bot_id: str) -> Dict[str, Any]:
        """Reset bot to idle state."""
        query = """
            UPDATE bots 
            SET current_job_id = NULL, 
                status = 'idle',
                health_status = 'normal',
                stuck_job_id = NULL
            WHERE id = $1
            RETURNING current_job_id
        """
        row = await self.connection.fetchrow(query, bot_id)
        return dict(row) if row else {}
    
    async def find_with_current_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Find bot that has a specific job assigned."""
        query = """
            SELECT * FROM bots 
            WHERE current_job_id = $1
        """
        row = await self.connection.fetchrow(query, job_id)
        return dict(row) if row else None
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get bot metrics."""
        query = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN NOW() - INTERVAL '2 minutes' > last_heartbeat_at THEN 1 ELSE 0 END) as down,
                SUM(CASE WHEN status = 'busy' AND NOW() - INTERVAL '2 minutes' <= last_heartbeat_at THEN 1 ELSE 0 END) as busy,
                SUM(CASE WHEN status = 'idle' AND NOW() - INTERVAL '2 minutes' <= last_heartbeat_at THEN 1 ELSE 0 END) as idle
            FROM bots 
            WHERE deleted_at IS NULL
        """
        row = await self.connection.fetchrow(query)
        return dict(row) if row else {
            "total": 0,
            "down": 0,
            "busy": 0,
            "idle": 0
        }