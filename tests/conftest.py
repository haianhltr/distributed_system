import asyncio
import os
import pytest
import asyncpg
from testcontainers.postgres import PostgresContainer
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Set test environment
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5433/testdb"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["DATALAKE_PATH"] = "/tmp/test_datalake"

from main_server.main import app
from main_server.database import DatabaseManager


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def postgres_container():
    """Start a PostgreSQL container for testing"""
    with PostgresContainer("postgres:16-alpine") as postgres:
        postgres.with_exposed_ports(5432)
        connection_url = postgres.get_connection_url()
        
        # Override DATABASE_URL for tests
        os.environ["DATABASE_URL"] = connection_url
        
        yield postgres


@pytest.fixture(scope="session")
async def db_manager(postgres_container):
    """Create and initialize database manager for testing"""
    manager = DatabaseManager(os.environ["DATABASE_URL"])
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
async def db_connection(db_manager):
    """Provide a clean database connection for each test"""
    async with db_manager.get_connection() as conn:
        async with conn.transaction():
            # Clean up tables before each test
            await conn.execute("DELETE FROM results")
            await conn.execute("DELETE FROM jobs") 
            await conn.execute("DELETE FROM bots")
            yield conn
            # Rollback happens automatically due to transaction context


@pytest.fixture
def client():
    """HTTP test client"""
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async HTTP test client"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
async def admin_headers():
    """Admin authentication headers"""
    return {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}


@pytest.fixture
async def sample_job(db_connection):
    """Create a sample job for testing"""
    job_id = "test-job-123"
    await db_connection.execute("""
        INSERT INTO jobs (id, a, b, status, created_at)
        VALUES ($1, $2, $3, 'pending', CURRENT_TIMESTAMP)
    """, job_id, 10, 20)
    return {"id": job_id, "a": 10, "b": 20}


@pytest.fixture 
async def sample_bot(db_connection):
    """Create a sample bot for testing"""
    bot_id = "test-bot-456"
    await db_connection.execute("""
        INSERT INTO bots (id, status, created_at, last_heartbeat_at)
        VALUES ($1, 'idle', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, bot_id)
    return {"id": bot_id, "status": "idle"}