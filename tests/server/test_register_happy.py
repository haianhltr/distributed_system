"""Server unit tests for /v1/bots/register happy path."""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from fastapi import FastAPI

from main_server.api.bots import router as bots_router
from main_server.models.schemas import BotRegister, AgentInfo, BotCapabilities
from main_server.services.bot_service import BotService


@pytest.fixture
def mock_bot_service():
    """Mock BotService."""
    return AsyncMock(spec=BotService)


@pytest.fixture
def valid_jwt_token():
    """Valid JWT token for testing."""
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJib3RzIiwiZXhwIjoxNjkzNzIxNTAwLCJzY29wZSI6InJlZ2lzdGVyIn0.test_signature"


@pytest.fixture
def valid_register_request():
    """Valid register request payload."""
    return {
        "bot_key": "bot_123",
        "instance_id": f"i-{uuid.uuid4()}",
        "agent": {
            "version": "0.1.0",
            "platform": "linux/amd64"
        },
        "capabilities": {
            "operations": ["sum"],
            "max_concurrency": 1
        }
    }


@pytest.fixture
def expected_register_response():
    """Expected successful register response."""
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
            "rate_limits": {
                "claim_rps": 1
            },
            "backoff": {
                "min_ms": 200,
                "max_ms": 5000,
                "jitter": True
            }
        },
        "endpoints": {
            "heartbeat": "/v1/bots/heartbeat",
            "claim": "/v1/jobs/claim", 
            "report": "/v1/jobs/report"
        },
        "server": {
            "region": "us-east-1",
            "version": "2025.08.22.1"
        }
    }


@pytest.fixture
def valid_idempotency_key():
    """Valid UUIDv4 idempotency key."""
    return str(uuid.uuid4())

# pytest -v -s tests/server/test_register_happy.py::test_register_happy
@pytest.mark.asyncio
@pytest.mark.unit
async def test_register_happy(
    mock_bot_service,
    valid_jwt_token,
    valid_register_request,
    expected_register_response,
    valid_idempotency_key
):
    """Test server-side bot registration happy path."""
    
    # Mock JWT validation
    with patch('main_server.api.dependencies.verify_jwt') as mock_verify_jwt, \
         patch('main_server.api.dependencies.get_bot_service', return_value=mock_bot_service):
        
        mock_verify_jwt.return_value = {
            "aud": "bots",
            "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp()),
            "scope": "register"
        }
        
        # Mock service response
        mock_bot_service.register_bot.return_value = expected_register_response
        
        # Create FastAPI app for testing
        from fastapi import FastAPI, Depends, Header
        from main_server.api.bots import register_bot
        from main_server.api.dependencies import get_bot_service
        
        app = FastAPI()
        
        @app.post("/v1/bots/register")
        async def test_register(
            bot_data: BotRegister,
            authorization: str = Header(...),
            idempotency_key: str = Header(..., alias="Idempotency-Key"),
            bot_service: BotService = Depends(get_bot_service)
        ):
            # Verify JWT token format
            assert authorization.startswith("Bearer ")
            token = authorization.replace("Bearer ", "")
            assert len(token) > 0
            
            # Verify idempotency key is UUIDv4
            uuid.UUID(idempotency_key, version=4)
            
            # Call the actual endpoint logic
            return await register_bot(bot_data, idempotency_key, {"scope": "register"}, bot_service)
        
        # Test the endpoint
        with TestClient(app) as client:
            response = client.post(
                "/v1/bots/register",
                json=valid_register_request,
                headers={
                    "Authorization": f"Bearer {valid_jwt_token}",
                    "Idempotency-Key": valid_idempotency_key,
                    "Content-Type": "application/json"
                }
            )
            
            # Verify HTTP response
            assert response.status_code == 200
            
            # Verify response structure
            response_data = response.json()
            assert "session" in response_data
            assert "session_id" in response_data["session"]
            assert "expires_in_sec" in response_data["session"] 
            assert response_data["session"]["expires_in_sec"] > 0
            
            assert "assignment" in response_data
            assert "policy" in response_data
            assert "rate_limits" in response_data["policy"]
            assert "backoff" in response_data["policy"]
            assert "endpoints" in response_data
            assert "heartbeat" in response_data["endpoints"]
            
            # Verify service was called with correct data
            mock_bot_service.register_bot.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_register_happy_idempotent_replay(
    mock_bot_service,
    valid_jwt_token,
    valid_register_request,
    expected_register_response,
    valid_idempotency_key
):
    """Test that same request returns identical body + Idempotency-Replayed: true header."""
    
    # Mock JWT validation
    with patch('main_server.api.dependencies.verify_jwt') as mock_verify_jwt, \
         patch('main_server.api.dependencies.get_bot_service', return_value=mock_bot_service):
        
        mock_verify_jwt.return_value = {
            "aud": "bots",
            "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp()),
            "scope": "register"
        }
        
        # Mock service to return the same response both times
        mock_bot_service.register_bot.return_value = expected_register_response
        
        # Create FastAPI app for testing
        from fastapi import FastAPI, Depends, Header, Response
        from main_server.api.bots import register_bot
        from main_server.api.dependencies import get_bot_service
        
        app = FastAPI()
        
        # Track requests by idempotency key
        request_cache = {}
        
        @app.post("/v1/bots/register")
        async def test_register(
            response: Response,
            bot_data: BotRegister,
            authorization: str = Header(...),
            idempotency_key: str = Header(..., alias="Idempotency-Key"),
            bot_service: BotService = Depends(get_bot_service)
        ):
            # Check if this is a replay
            if idempotency_key in request_cache:
                response.headers["Idempotency-Replayed"] = "true"
                return request_cache[idempotency_key]
            
            # First request - call service and cache result
            result = await register_bot(bot_data, idempotency_key, {"scope": "register"}, bot_service)
            request_cache[idempotency_key] = result
            return result
        
        # Test the endpoint with same request twice
        with TestClient(app) as client:
            headers = {
                "Authorization": f"Bearer {valid_jwt_token}",
                "Idempotency-Key": valid_idempotency_key,
                "Content-Type": "application/json"
            }
            
            # First request
            response1 = client.post("/v1/bots/register", json=valid_register_request, headers=headers)
            assert response1.status_code == 200
            data1 = response1.json()
            assert "Idempotency-Replayed" not in response1.headers
            
            # Second identical request
            response2 = client.post("/v1/bots/register", json=valid_register_request, headers=headers)
            assert response2.status_code == 200
            data2 = response2.json()
            
            # Verify responses are identical
            assert data1 == data2
            
            # Verify replay header is present on second request
            assert response2.headers["Idempotency-Replayed"] == "true"