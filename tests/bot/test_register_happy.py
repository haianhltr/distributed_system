"""Bot unit tests for /v1/bots/register happy path."""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bots.services.http_client import HttpClient
from bots.config.settings import BotConfig


@pytest.fixture
def mock_config():
    """Mock bot configuration."""
    config = MagicMock(spec=BotConfig)
    config.bot_id = "test_bot_123"
    config.main_server_url = "http://localhost:8000"
    config.bootstrap_secret = "test_bootstrap_secret"
    # Fix circuit breaker config values
    config.circuit_breaker_failure_threshold = 5
    config.circuit_breaker_recovery_timeout = 30
    config.circuit_breaker_half_open_max_calls = 3
    return config


@pytest.fixture
def http_client(mock_config):
    """Create HttpClient instance with mocked config."""
    return HttpClient(mock_config)


@pytest.fixture
def mock_jwt_response():
    """Mock JWT token response."""
    return {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJib3RzIiwiZXhwIjoxNjkzNzIxNTAwLCJzY29wZSI6InJlZ2lzdGVyIn0.test_signature",
        "token_type": "Bearer",
        "expires_in": 900
    }


@pytest.fixture
def mock_register_response():
    """Mock successful register response."""
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


# pytest -v -s tests/bot/test_register_happy.py::test_register_happy
@pytest.mark.asyncio
async def test_register_happy(
    http_client,
    mock_jwt_response,
    mock_register_response
):
    """Test bot registration happy path - validates request structure and response parsing."""
    
    # Mock the _get_jwt_token and direct HTTP calls instead of mocking session
    with patch.object(http_client, '_get_jwt_token', return_value=True) as mock_get_jwt, \
         patch.object(http_client, 'session') as mock_session:
        
        # Set access token
        http_client.access_token = mock_jwt_response['access_token']
        
        # Mock the session.post for register call
        register_ctx = AsyncMock()
        register_response = AsyncMock()
        register_response.status = 200
        register_response.json = AsyncMock(return_value=mock_register_response)
        register_ctx.__aenter__ = AsyncMock(return_value=register_response)
        register_ctx.__aexit__ = AsyncMock(return_value=False)
        
        mock_session.post.return_value = register_ctx
        
        # Execute registration
        success = await http_client.register_bot()
        
        # Verify success
        assert success is True
        
        # Verify JWT token was requested
        mock_get_jwt.assert_called_once()
        
        # Verify register request
        register_call = mock_session.post.call_args_list[0]
        
        # Check URL
        assert register_call[0][0].endswith('/v1/bots/register')
        
        # Check headers
        headers = register_call[1]['headers']
        assert 'Authorization' in headers
        assert headers['Authorization'] == f"Bearer {mock_jwt_response['access_token']}"
        assert 'Idempotency-Key' in headers
        assert headers['Content-Type'] == 'application/json'
        
        # Validate UUIDv4 format for idempotency key
        idempotency_key = headers['Idempotency-Key']
        uuid.UUID(idempotency_key, version=4)  # Will raise if not valid UUIDv4
        
        # Check request body structure
        request_body = register_call[1]['json']
        assert request_body['bot_key'] == "test_bot_123"
        assert request_body['instance_id'].startswith('i-')
        assert request_body['agent']['version'] == "0.1.0"
        assert request_body['agent']['platform'] == "linux/amd64"
        assert request_body['capabilities']['operations'] == ["sum"]
        assert request_body['capabilities']['max_concurrency'] == 1
        
        # Verify response parsing and session caching
        assert http_client.session_id == mock_register_response['session']['session_id']
        assert http_client.session_expires_in == mock_register_response['session']['expires_in_sec']
        assert http_client.heartbeat_interval == mock_register_response['session']['heartbeat_interval_sec']