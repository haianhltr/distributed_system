"""
Shared test configuration and fixtures for bot registration tests.

This provides mock database setup for testing.
"""

import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from main import app, db_manager


@pytest.fixture
def mock_db_connection():
    """Create a mock database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.transaction = MagicMock()
    conn.transaction.__aenter__ = AsyncMock()
    conn.transaction.__aexit__ = AsyncMock()
    return conn


@pytest.fixture
def client_with_db(mock_db_connection):
    """Test client with mocked database."""
    # Create async context manager for get_connection
    class MockContextManager:
        async def __aenter__(self):
            return mock_db_connection
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    # Mock the db_manager methods - return the context manager directly
    db_manager.get_connection = lambda: MockContextManager()
    db_manager.pool = MagicMock()  # Ensure pool is not None
    
    yield TestClient(app), mock_db_connection
    
    # Reset after test
    db_manager.pool = None
