"""Base repository with common database operations."""

from typing import Optional, List, Dict, Any, TypeVar, Generic
from abc import ABC, abstractmethod
import asyncpg
from datetime import datetime

T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """Base repository providing common database operations."""
    
    def __init__(self, connection: asyncpg.Connection):
        self.connection = connection
    
    @property
    @abstractmethod
    def table_name(self) -> str:
        """Return the table name for this repository."""
        pass
    
    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a single record by ID."""
        query = f"SELECT * FROM {self.table_name} WHERE id = $1"
        row = await self.connection.fetchrow(query, id)
        return dict(row) if row else None
    
    async def find_all(
        self, 
        limit: int = 100, 
        offset: int = 0,
        order_by: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Find all records with pagination."""
        query = f"SELECT * FROM {self.table_name}"
        if order_by:
            query += f" ORDER BY {order_by}"
        query += " LIMIT $1 OFFSET $2"
        
        rows = await self.connection.fetch(query, limit, offset)
        return [dict(row) for row in rows]
    
    async def count(self, where: Optional[str] = None, params: Optional[List[Any]] = None) -> int:
        """Count records matching criteria."""
        query = f"SELECT COUNT(*) FROM {self.table_name}"
        if where:
            query += f" WHERE {where}"
        
        if params:
            count = await self.connection.fetchval(query, *params)
        else:
            count = await self.connection.fetchval(query)
        
        return count or 0
    
    async def exists(self, id: str) -> bool:
        """Check if a record exists by ID."""
        query = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE id = $1)"
        return await self.connection.fetchval(query, id)
    
    async def delete(self, id: str) -> bool:
        """Delete a record by ID."""
        query = f"DELETE FROM {self.table_name} WHERE id = $1"
        result = await self.connection.execute(query, id)
        return result.split()[-1] == "1"
    
    async def execute_query(self, query: str, *params) -> List[Dict[str, Any]]:
        """Execute a custom query and return results."""
        rows = await self.connection.fetch(query, *params)
        return [dict(row) for row in rows]
    
    async def execute_command(self, query: str, *params) -> str:
        """Execute a command (INSERT, UPDATE, DELETE) and return result."""
        return await self.connection.execute(query, *params)