"""Tests for Auth Token Issuance (A1) endpoint."""

import pytest
import jwt
import bcrypt
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from main_server.main import app
from main_server.api.auth import JWT_ALGORITHM, JWT_ISSUER, JWT_AUDIENCE, PUBLIC_KEY, KID


class TestAuthTokenHappy:
    """Test successful authentication flow."""
    
    @pytest.fixture
    def valid_bot_data(self):
        """Create test bot with hashed secret."""
        secret = "test-secret-123"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        return {
            "bot_key": "bot-123",
            "bootstrap_secret": secret,
            "bootstrap_secret_hash": hashed,
            "is_enabled": True
        }

    @pytest.fixture  
    def mock_uow(self, valid_bot_data):
        """Mock unit of work with database operations."""
        uow = AsyncMock()
        uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.return_value = {
            'bot_key': valid_bot_data['bot_key'],
            'bootstrap_secret_hash': valid_bot_data['bootstrap_secret_hash'],
            'is_enabled': valid_bot_data['is_enabled']
        }
        uow.db_pool.acquire.return_value.__aenter__.return_value.execute.return_value = None
        return uow

    def test_auth_token_happy(self, valid_bot_data, mock_uow):
        """Test successful token issuance with valid credentials."""
        client = TestClient(app)
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow
            
            response = client.post(
                "/v1/auth/token",
                json={
                    "bot_key": valid_bot_data['bot_key'],
                    "bootstrap_secret": valid_bot_data['bootstrap_secret']
                },
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0
        assert "issued_at" in data
        
        # Verify JWT can be decoded and has correct claims
        token = data["access_token"]
        decoded = jwt.decode(
            token, 
            PUBLIC_KEY, 
            algorithms=[JWT_ALGORITHM],
            options={"verify_signature": False}  # Skip signature verification for test
        )
        
        assert decoded["sub"] == valid_bot_data['bot_key']
        assert decoded["aud"] == JWT_AUDIENCE
        assert decoded["iss"] == JWT_ISSUER
        assert "iat" in decoded
        assert "exp" in decoded
        assert "jti" in decoded
        assert decoded["exp"] > decoded["iat"]
        
        # Check token validity period (should be 600-1800 seconds)
        token_lifetime = decoded["exp"] - decoded["iat"]
        assert 600 <= token_lifetime <= 1800


class TestAuthTokenErrors:
    """Test error cases for token issuance."""
    
    @pytest.fixture
    def mock_uow_unknown_bot(self):
        """Mock UoW that returns no bot for lookup."""
        uow = AsyncMock()
        uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.return_value = None
        uow.db_pool.acquire.return_value.__aenter__.return_value.execute.return_value = None
        return uow

    @pytest.fixture
    def mock_uow_wrong_secret(self):
        """Mock UoW with bot that has different secret."""
        secret = "correct-secret"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        uow = AsyncMock()
        uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.return_value = {
            'bot_key': 'bot-123',
            'bootstrap_secret_hash': hashed,
            'is_enabled': True
        }
        uow.db_pool.acquire.return_value.__aenter__.return_value.execute.return_value = None
        return uow

    def test_auth_token_invalid_secret_401(self, mock_uow_wrong_secret):
        """Test authentication failure with wrong secret."""
        client = TestClient(app)
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow_wrong_secret
            
            response = client.post(
                "/v1/auth/token",
                json={
                    "bot_key": "bot-123",
                    "bootstrap_secret": "wrong-secret"
                },
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "UNAUTHENTICATED"
        assert "Invalid credentials" in data["message"]
        assert data["retryable"] == False

    def test_auth_token_unknown_bot_401(self, mock_uow_unknown_bot):
        """Test authentication failure with unknown bot_key."""
        client = TestClient(app)
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow_unknown_bot
            
            response = client.post(
                "/v1/auth/token",
                json={
                    "bot_key": "unknown-bot",
                    "bootstrap_secret": "any-secret"
                },
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "UNAUTHENTICATED"
        assert "Invalid credentials" in data["message"]
        
        # Should be same error as wrong secret (no information leakage)
        assert data == {
            "error_code": "UNAUTHENTICATED",
            "message": "Invalid credentials",
            "retryable": False,
            "backoff_ms": 0
        }


class TestAuthTokenNiceToHave:
    """Nice-to-have test cases from A1 specification."""
    
    @pytest.fixture
    def mock_uow_revoked_bot(self):
        """Mock UoW with disabled/revoked bot."""
        secret = "test-secret"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        uow = AsyncMock()
        uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.return_value = {
            'bot_key': 'revoked-bot',
            'bootstrap_secret_hash': hashed,
            'is_enabled': False  # Bot is disabled
        }
        return uow

    @pytest.fixture
    def mock_uow_rate_limited(self):
        """Mock UoW with rate-limited bot."""
        secret = "test-secret"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        
        # Mock guard table returning a lock
        future_time = datetime.utcnow() + timedelta(minutes=5)
        
        uow = AsyncMock()
        # First call for auth guard check
        uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.side_effect = [
            {'failed_attempts': 5, 'locked_until': future_time},  # Guard check
            {'bot_key': 'rate-limited-bot', 'bootstrap_secret_hash': hashed, 'is_enabled': True}  # Bot lookup
        ]
        return uow

    def test_auth_token_revoked_bot_403(self, mock_uow_revoked_bot):
        """Test that revoked/disabled bot gets 403."""
        client = TestClient(app)
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow_revoked_bot
            
            response = client.post(
                "/v1/auth/token",
                json={
                    "bot_key": "revoked-bot",
                    "bootstrap_secret": "test-secret"
                },
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 403
        data = response.json()
        assert data["error_code"] == "FORBIDDEN"
        assert "revoked" in data["message"]
        assert data["retryable"] == False

    def test_auth_token_rate_limited_429(self, mock_uow_rate_limited):
        """Test rate limiting after multiple failures."""
        client = TestClient(app)
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow_rate_limited
            
            response = client.post(
                "/v1/auth/token",
                json={
                    "bot_key": "rate-limited-bot",
                    "bootstrap_secret": "test-secret"
                },
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 429
        data = response.json()
        assert data["error_code"] == "RATE_LIMITED"
        assert "Retry-After" in response.headers
        assert data["retryable"] == True
        assert data["backoff_ms"] > 0

    def test_auth_token_claims_shape_and_kid(self):
        """Test JWT has proper structure, claims, and kid header."""
        client = TestClient(app)
        
        # Mock successful authentication
        secret = "test-secret"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        
        mock_uow = AsyncMock()
        mock_uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.side_effect = [
            None,  # No auth guard lock
            {'bot_key': 'bot-123', 'bootstrap_secret_hash': hashed, 'is_enabled': True}
        ]
        mock_uow.db_pool.acquire.return_value.__aenter__.return_value.execute.return_value = None
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow
            
            response = client.post(
                "/v1/auth/token",
                json={"bot_key": "bot-123", "bootstrap_secret": "test-secret"},
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 200
        token = response.json()["access_token"]
        
        # Decode without verification to check structure
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert header["kid"] == KID
        
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["iss"] == JWT_ISSUER
        assert payload["aud"] == JWT_AUDIENCE
        assert payload["sub"] == "bot-123"
        assert "iat" in payload
        assert "exp" in payload
        assert "jti" in payload

    def test_auth_token_exp_is_short_lived(self):
        """Test that token expiry is between 600-1800 seconds."""
        client = TestClient(app)
        
        # Mock successful authentication
        secret = "test-secret"
        hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt())
        
        mock_uow = AsyncMock()
        mock_uow.db_pool.acquire.return_value.__aenter__.return_value.fetchrow.side_effect = [
            None,  # No auth guard lock
            {'bot_key': 'bot-123', 'bootstrap_secret_hash': hashed, 'is_enabled': True}
        ]
        mock_uow.db_pool.acquire.return_value.__aenter__.return_value.execute.return_value = None
        
        with patch('main_server.api.auth.get_unit_of_work') as mock_get_uow:
            mock_get_uow.return_value = mock_uow
            
            response = client.post(
                "/v1/auth/token",
                json={"bot_key": "bot-123", "bootstrap_secret": "test-secret"},
                headers={"X-Client-Version": "1.0.0"}
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check expires_in is in valid range
        assert 600 <= data["expires_in"] <= 1800
        
        # Also verify the JWT exp claim
        token = data["access_token"]
        payload = jwt.decode(token, options={"verify_signature": False})
        token_lifetime = payload["exp"] - payload["iat"]
        assert 600 <= token_lifetime <= 1800

    def test_outdated_client_version_426(self):
        """Test that outdated client version gets 426."""
        client = TestClient(app)
        
        response = client.post(
            "/v1/auth/token",
            json={"bot_key": "bot-123", "bootstrap_secret": "secret"},
            headers={"X-Client-Version": "0.9.0"}  # Below minimum 1.0.0
        )
        
        assert response.status_code == 426
        data = response.json()
        assert data["error_code"] == "OUTDATED_CLIENT"
        assert "too old" in data["message"]
        assert data["retryable"] == False


class TestJWKSEndpoint:
    """Test JWKS endpoint for public key distribution."""
    
    def test_jwks_endpoint_returns_public_key(self):
        """Test that JWKS endpoint returns proper public key."""
        client = TestClient(app)
        
        response = client.get("/v1/auth/.well-known/jwks")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "keys" in data
        assert len(data["keys"]) == 1
        
        key = data["keys"][0]
        assert key["kty"] == "RSA"
        assert key["kid"] == KID
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert "n" in key  # Public key modulus
        assert "e" in key  # Public key exponent