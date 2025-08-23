"""Simple server test for bot registration endpoint."""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    
    @app.post("/v1/bots/register")
    async def register_bot(request_data: dict):
        # Mock successful registration response
        return {
            "bot_id": "b_01ABC",
            "registered_at": "2025-08-22T00:01:00Z",
            "session": {
                "session_id": "s_01XYZ",
                "expires_in_sec": 900,
                "heartbeat_interval_sec": 30
            },
            "assignment": {
                "operation": None,
                "queue": None,
                "max_concurrency": 1
            },
            "policy": {
                "rate_limits": {"claim_rps": 1},
                "backoff": {"min_ms": 200, "max_ms": 5000, "jitter": True}
            },
            "endpoints": {
                "heartbeat": "/v1/bots/heartbeat",
                "claim": "/v1/jobs/claim",
                "report": "/v1/jobs/report"
            },
            "server": {"region": "us-east-1", "version": "2025.08.22.1"}
        }
    
    return app


def test_register_simple_happy_path(app):
    """Test basic registration endpoint structure."""
    with TestClient(app) as client:
        request_data = {
            "bot_key": "test_bot_123",
            "instance_id": f"i-{uuid.uuid4()}",
            "agent": {"version": "0.1.0", "platform": "linux/amd64"},
            "capabilities": {"operations": ["sum"], "max_concurrency": 1}
        }
        
        headers = {
            "Authorization": "Bearer test_token",
            "Idempotency-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
        
        response = client.post("/v1/bots/register", json=request_data, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "session" in data
        assert "session_id" in data["session"]
        assert data["session"]["expires_in_sec"] == 900
        assert "assignment" in data
        assert "policy" in data
        assert "endpoints" in data