"""Unit of Work pattern for managing database transactions."""

from typing import Optional
from contextlib import asynccontextmanager
import asyncpg

from .job_repository import JobRepository
from .bot_repository import BotRepository
from .result_repository import ResultRepository


class UnitOfWork:
    """Unit of Work pattern implementation for transaction management."""
    
    def __init__(self, connection: asyncpg.Connection):
        self.connection = connection
        self._jobs: Optional[JobRepository] = None
        self._bots: Optional[BotRepository] = None
        self._results: Optional[ResultRepository] = None
    
    @property
    def jobs(self) -> JobRepository:
        """Get job repository instance."""
        if self._jobs is None:
            self._jobs = JobRepository(self.connection)
        return self._jobs
    
    @property
    def bots(self) -> BotRepository:
        """Get bot repository instance."""
        if self._bots is None:
            self._bots = BotRepository(self.connection)
        return self._bots
    
    @property
    def results(self) -> ResultRepository:
        """Get result repository instance."""
        if self._results is None:
            self._results = ResultRepository(self.connection)
        return self._results
    
    async def execute_query(self, query: str, *params):
        """Execute a raw query."""
        return await self.connection.fetch(query, *params)
    
    async def execute_command(self, query: str, *params):
        """Execute a raw command."""
        return await self.connection.execute(query, *params)


@asynccontextmanager
async def create_unit_of_work(db_pool: asyncpg.Pool):
    """Create a unit of work with transaction support."""
    async with db_pool.acquire() as connection:
        async with connection.transaction():
            yield UnitOfWork(connection)