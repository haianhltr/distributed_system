"""End-to-end tests for /v1/bots/register happy path."""

import pytest
import uuid
import aiohttp
from typing import Dict, Any


@pytest.fixture
def server_base_url():
    """Base URL for the main server."""
    return "http://localhost:8000"


@pytest.fixture
def bot_credentials():
    """Bot credentials for authentication."""
    return {
        "bot_key": "test_bot_e2e",
        "bootstrap_secret": "test_bootstrap_secret"
    }


@pytest.fixture
def fresh_instance_id():
    """Generate fresh instance ID for each test."""
    return f"i-{uuid.uuid4()}"


@pytest.fixture 
def register_payload(bot_credentials, fresh_instance_id):
    """Complete register request payload."""
    return {
        "bot_key": bot_credentials["bot_key"],
        "instance_id": fresh_instance_id,
        "agent": {
            "version": "0.1.0", 
            "platform": "linux/amd64"
        },
        "capabilities": {
            "operations": ["sum"],
            "max_concurrency": 1
        }
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_register_happy_e2e(
    server_base_url: str,
    bot_credentials: Dict[str, str], 
    register_payload: Dict[str, Any]
):
    """Test complete bot registration flow end-to-end."""
    
    async with aiohttp.ClientSession() as session:
        # Step 1: Get JWT token from /v1/auth/token
        auth_response = await session.post(
            f"{server_base_url}/v1/auth/token",
            json={
                "bot_key": bot_credentials["bot_key"],
                "bootstrap_secret": bot_credentials["bootstrap_secret"]
            },
            headers={"Content-Type": "application/json"}
        )
        
        assert auth_response.status == 200, f"Auth failed with status {auth_response.status}"
        
        auth_data = await auth_response.json()
        assert "access_token" in auth_data
        assert "token_type" in auth_data
        assert auth_data["token_type"] == "Bearer"
        
        access_token = auth_data["access_token"]
        
        # Step 2: Register bot using JWT + Idempotency-Key
        idempotency_key = str(uuid.uuid4())
        
        register_response = await session.post(
            f"{server_base_url}/v1/bots/register",
            json=register_payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/json"
            }
        )
        
        assert register_response.status == 200, f"Registration failed with status {register_response.status}"
        
        # Step 3: Verify response structure per contract
        response_data = await register_response.json()
        
        # Verify top-level fields
        assert "bot_id" in response_data
        assert "registered_at" in response_data
        assert "session" in response_data
        assert "assignment" in response_data
        assert "policy" in response_data
        assert "endpoints" in response_data
        assert "server" in response_data
        
        # Verify session details
        session_info = response_data["session"]
        assert "session_id" in session_info
        assert "expires_in_sec" in session_info
        assert "heartbeat_interval_sec" in session_info
        
        assert len(session_info["session_id"]) > 0
        assert isinstance(session_info["expires_in_sec"], int)
        assert session_info["expires_in_sec"] > 0
        assert isinstance(session_info["heartbeat_interval_sec"], int)
        assert session_info["heartbeat_interval_sec"] > 0
        
        # Verify assignment structure
        assignment = response_data["assignment"]
        assert "operation" in assignment
        assert "queue" in assignment  
        assert "max_concurrency" in assignment
        
        # Verify policy structure
        policy = response_data["policy"]
        assert "rate_limits" in policy
        assert "backoff" in policy
        
        rate_limits = policy["rate_limits"]
        assert "claim_rps" in rate_limits
        assert isinstance(rate_limits["claim_rps"], (int, float))
        
        backoff = policy["backoff"]
        assert "min_ms" in backoff
        assert "max_ms" in backoff
        assert "jitter" in backoff
        assert isinstance(backoff["min_ms"], int)
        assert isinstance(backoff["max_ms"], int)
        assert isinstance(backoff["jitter"], bool)
        
        # Verify endpoints structure
        endpoints = response_data["endpoints"]
        assert "heartbeat" in endpoints
        assert "claim" in endpoints
        assert "report" in endpoints
        assert endpoints["heartbeat"] == "/v1/bots/heartbeat"
        assert endpoints["claim"] == "/v1/jobs/claim"
        assert endpoints["report"] == "/v1/jobs/report"
        
        # Verify server info
        server_info = response_data["server"]
        assert "region" in server_info
        assert "version" in server_info


@pytest.mark.asyncio
@pytest.mark.integration
async def test_register_happy_idempotent_replay_e2e(
    server_base_url: str,
    bot_credentials: Dict[str, str],
    register_payload: Dict[str, Any]
):
    """Test idempotency - same request returns identical response with replay header."""
    
    async with aiohttp.ClientSession() as session:
        # Get auth token
        auth_response = await session.post(
            f"{server_base_url}/v1/auth/token",
            json=bot_credentials,
            headers={"Content-Type": "application/json"}
        )
        
        auth_data = await auth_response.json()
        access_token = auth_data["access_token"]
        
        # Use same idempotency key for both requests
        idempotency_key = str(uuid.uuid4())
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json"
        }
        
        # First request
        response1 = await session.post(
            f"{server_base_url}/v1/bots/register",
            json=register_payload,
            headers=headers
        )
        
        assert response1.status == 200
        data1 = await response1.json()
        
        # Second identical request
        response2 = await session.post(
            f"{server_base_url}/v1/bots/register", 
            json=register_payload,
            headers=headers
        )
        
        assert response2.status == 200
        data2 = await response2.json()
        
        # Verify responses are identical
        assert data1 == data2
        
        # Verify replay header is present on second request
        assert "Idempotency-Replayed" in response2.headers
        assert response2.headers["Idempotency-Replayed"] == "true"