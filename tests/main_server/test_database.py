import pytest
from main_server.database import DatabaseManager


@pytest.mark.asyncio
class TestDatabaseManager:
    """Test database manager functionality"""
    
    async def test_initialization(self, db_manager):
        """Test database initialization"""
        assert db_manager is not None
        assert db_manager.pool is not None
    
    async def test_connection_pool(self, db_manager):
        """Test connection pool functionality"""
        async with db_manager.get_connection() as conn:
            result = await conn.fetchval("SELECT 1")
            assert result == 1
    
    async def test_concurrent_connections(self, db_manager):
        """Test multiple concurrent connections"""
        async def query_db():
            async with db_manager.get_connection() as conn:
                return await conn.fetchval("SELECT 1")
        
        import asyncio
        results = await asyncio.gather(
            query_db(), query_db(), query_db(), query_db(), query_db()
        )
        assert all(r == 1 for r in results)


@pytest.mark.asyncio  
class TestDatabaseSchema:
    """Test database schema and constraints"""
    
    async def test_jobs_table_structure(self, db_connection):
        """Test jobs table exists with correct structure"""
        result = await db_connection.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'jobs'
            ORDER BY ordinal_position
        """)
        
        columns = {r['column_name']: r for r in result}
        assert 'id' in columns
        assert 'a' in columns  
        assert 'b' in columns
        assert 'status' in columns
        assert 'created_at' in columns
    
    async def test_bots_table_structure(self, db_connection):
        """Test bots table exists with correct structure"""
        result = await db_connection.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'bots'
            ORDER BY ordinal_position
        """)
        
        columns = {r['column_name']: r for r in result}
        assert 'id' in columns
        assert 'status' in columns
        assert 'current_job_id' in columns
        assert 'last_heartbeat_at' in columns
    
    async def test_results_table_structure(self, db_connection):
        """Test results table exists with correct structure"""
        result = await db_connection.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'results'
            ORDER BY ordinal_position
        """)
        
        columns = {r['column_name']: r for r in result}
        assert 'id' in columns
        assert 'job_id' in columns
        assert 'processed_by' in columns
        assert 'sum' in columns
        assert 'duration_ms' in columns
    
    async def test_job_status_constraint(self, db_connection):
        """Test job status constraint works"""
        with pytest.raises(Exception):  # Should fail with invalid status
            await db_connection.execute("""
                INSERT INTO jobs (id, a, b, status, created_at)
                VALUES ('test-invalid-status', 1, 2, 'invalid', CURRENT_TIMESTAMP)
            """)
    
    async def test_bot_status_constraint(self, db_connection):
        """Test bot status constraint works"""
        with pytest.raises(Exception):  # Should fail with invalid status
            await db_connection.execute("""
                INSERT INTO bots (id, status, created_at, last_heartbeat_at)
                VALUES ('test-invalid-bot', 'invalid', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)
    
    async def test_indexes_exist(self, db_connection):
        """Test that performance indexes exist"""
        result = await db_connection.fetch("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename IN ('jobs', 'bots', 'results')
        """)
        
        index_names = [r['indexname'] for r in result]
        assert 'idx_jobs_status' in index_names
        assert 'idx_jobs_claimed_by' in index_names
        assert 'idx_bots_status' in index_names