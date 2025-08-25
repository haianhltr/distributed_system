        """Tests for Bot Auth Client (A1) functionality."""

import pytest
        import asyncio
        import json
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, Mock, patch
        from aiohttp import ClientSession, web
        from aiohttp.test_utils import make_mocked_coro
        import pprint

        from bots.auth_client import AuthClient
        from bots.exceptions import AuthenticationError, RateLimitError, BotClientError


        class TestBotAuthClientHappy:
            """Test successful authentication flows."""

            @pytest.fixture
            def auth_config(self):
                """Standard auth client configuration."""
                return {
                    "bot_key": "test-bot-123",
                    "bootstrap_secret": "test-secret-456",
                    "auth_endpoint": "http://localhost:8000/v1/auth/token",
                    "token_refresh_skew_seconds": 60,
                    "client_version": "1.0.0"
                }

            @pytest.fixture
            def mock_session(self):
                """Mock aiohttp session."""
                return AsyncMock(spec=ClientSession)

            @pytest.fixture
            def success_response_data(self):
                """Successful token response data."""
                return {
                    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "issued_at": "2025-08-25T10:30:00Z"
                }

            #  pytest -v -s tests/bot/test_auth_client.py::TestBotAuthClientHappy::test_bot_obtains_access_token_happy
            @pytest.mark.asyncio
            async def test_bot_obtains_access_token_happy(self, auth_config, mock_session, success_response_data):
                """Test bot successfully obtains and stores access token."""

                # Pretty printer for nicer output
                pp = pprint.PrettyPrinter(indent=2)

                print("\n[SETUP] Creating fake aiohttp response with success data")
                print("[INFO] success_response_data:")
                pp.pprint(success_response_data)

                # Mock successful HTTP response
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = make_mocked_coro(success_response_data)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                # Create auth client and obtain token
                auth_client = AuthClient(auth_config, mock_session)
                await auth_client.obtain_token()

                print("\n[STATE] AuthClient object after obtain_token():")
                pp.pprint(auth_client.__dict__)  # show all attributes of AuthClient

                # Verify token stored correctly
                assert auth_client.access_token == success_response_data["access_token"]
                assert auth_client.token_type == "Bearer"
                assert auth_client.expires_at is not None

                # Verify can build Authorization header
                auth_header = auth_client.get_auth_header()
                print("\n[STATE] Authorization header built by client:")
                pp.pprint(auth_header)

                # Verify HTTP call made correctly
                print("\n[STATE] Mock session POST call args:")
                pp.pprint(mock_session.post.call_args)  # shows what arguments were passed

                mock_session.post.assert_called_once_with(
                    auth_config["auth_endpoint"],
                    json={
                        "bot_key": auth_config["bot_key"],
                        "bootstrap_secret": auth_config["bootstrap_secret"]
                    },
                    headers={
                        "X-Client-Version": "1.0.0",
                        "Content-Type": "application/json"
                    }
                )

                print("\n[RESULT] Test completed successfully ✅")

            # pytest -v -s tests/bot/test_auth_client.py::TestBotAuthClientHappy::test_bot_stores_expiry_and_bearer_header_builder
            @pytest.mark.asyncio
            async def test_bot_stores_expiry_and_bearer_header_builder(self, auth_config, mock_session, success_response_data):
                """Test token expiry calculation and header building."""

                # Mock response with 120 second expiry
                response_data = success_response_data.copy()
                response_data["expires_in"] = 120
                response_data["issued_at"] = "2025-08-25T10:30:00Z"

                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = make_mocked_coro(response_data)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                with patch('bots.auth_cli.ent.datetime') as mock_datetime:
                    # Mock current time
                    current_time = datetime(2025, 8, 25, 10, 30, 0)
                    mock_datetime.fromisoformat.return_value = current_time
                    mock_datetime.utcnow.return_value = current_time

                    await auth_client.obtain_token()

                    # First call - should have fresh token
                    assert auth_client.is_token_fresh() == True
                    header1 = auth_client.get_auth_header()

                    # Simulate time passing but still within expiry (considering 60s skew)
                    # Token expires at issued_at + 120s - 60s skew = issued_at + 60s
                    mock_datetime.utcnow.return_value = current_time + timedelta(seconds=30)

                    # Second call - should still be fresh, same token
                    assert auth_client.is_token_fresh() == True  
                    header2 = auth_client.get_auth_header()

                    # Should be same token (no re-auth happened)
                    assert header1 == header2
                    assert mock_session.post.call_count == 1


        class TestBotAuthClientErrors:
            """Test error handling scenarios."""

            @pytest.fixture
            def auth_config(self):
                return {
                    "bot_key": "test-bot",
                    "bootstrap_secret": "secret",
                    "auth_endpoint": "http://localhost:8000/v1/auth/token",
                    "client_version": "1.0.0"
                }

            @pytest.fixture
            def mock_session(self):
                return AsyncMock(spec=ClientSession)

            @pytest.mark.asyncio
            async def test_bot_handles_401_and_surfaces_error(self, auth_config, mock_session):
                """Test bot handles 401 authentication error correctly."""

                error_response = {
                    "error_code": "UNAUTHENTICATED",
                    "message": "Invalid credentials",
                    "retryable": False,
                    "backoff_ms": 0
                }

                mock_response = AsyncMock()
                mock_response.status = 401
                mock_response.json = make_mocked_coro(error_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                # Should raise AuthenticationError, not retry, and not log secret
                with pytest.raises(AuthenticationError) as exc_info:
                    await auth_client.obtain_token()

                assert "UNAUTHENTICATED" in str(exc_info.value)
                assert "Invalid credentials" in str(exc_info.value)

                # Should only make one attempt (no retry on 401)
                assert mock_session.post.call_count == 1

                # Token should not be stored
                assert auth_client.access_token is None

            @pytest.mark.asyncio  
            async def test_bot_respects_retry_after_on_429(self, auth_config, mock_session):
                """Test bot respects Retry-After header on 429 rate limit."""

                rate_limit_response = {
                    "error_code": "RATE_LIMITED", 
                    "message": "Too many attempts",
                    "retryable": True,
                    "backoff_ms": 3000
                }

                success_response = {
                    "access_token": "token123",
                    "token_type": "Bearer", 
                    "expires_in": 900,
                    "issued_at": "2025-08-25T10:30:00Z"
                }

                # First response: 429 with Retry-After: 3
                mock_response_429 = AsyncMock()
                mock_response_429.status = 429
                mock_response_429.headers = {"Retry-After": "3"}
                mock_response_429.json = make_mocked_coro(rate_limit_response)

                # Second response: 200 success
                mock_response_200 = AsyncMock()
                mock_response_200.status = 200
                mock_response_200.json = make_mocked_coro(success_response)

                # Configure session to return different responses on subsequent calls
                mock_session.post.return_value.__aenter__.side_effect = [
                    mock_response_429,
                    mock_response_200
                ]

                auth_client = AuthClient(auth_config, mock_session)

                with patch('bots.auth_client.asyncio.sleep') as mock_sleep:
                    await auth_client.obtain_token()

                    # Should have slept for 3 seconds as specified in Retry-After
                    mock_sleep.assert_called_once_with(3)

                # Should have made two calls (initial + retry)
                assert mock_session.post.call_count == 2

                # Should have successfully stored token after retry
                assert auth_client.access_token == "token123"

            @pytest.mark.asyncio
            async def test_bot_does_not_log_bootstrap_secret(self, auth_config, mock_session, caplog):
                """Test that bootstrap secret is never logged."""

                # Test with successful response
                success_response = {
                    "access_token": "token123",
                    "token_type": "Bearer",
                    "expires_in": 900, 
                    "issued_at": "2025-08-25T10:30:00Z"
                }

                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = make_mocked_coro(success_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                with caplog.at_level('DEBUG'):
                    await auth_client.obtain_token()

                # Check all log messages
                all_log_text = ' '.join([record.message for record in caplog.records])

                # Should contain bot_key but never the secret
                assert auth_config["bot_key"] in all_log_text
                assert auth_config["bootstrap_secret"] not in all_log_text

                # Test with error response to ensure secret not logged in error case
                caplog.clear()

                error_response = {
                    "error_code": "UNAUTHENTICATED",
                    "message": "Invalid credentials",
                    "retryable": False
                }

                mock_error_response = AsyncMock()
                mock_error_response.status = 401
                mock_error_response.json = make_mocked_coro(error_response)
                mock_session.post.return_value.__aenter__.return_value = mock_error_response

                with caplog.at_level('DEBUG'):
                    with pytest.raises(AuthenticationError):
                        await auth_client.obtain_token()

                # Check error logs also don't contain secret
                all_error_log_text = ' '.join([record.message for record in caplog.records])
                assert auth_config["bootstrap_secret"] not in all_error_log_text


        class TestBotAuthClientNiceToHave:
            """Additional test cases for comprehensive coverage."""

            @pytest.fixture
            def auth_config(self):
                return {
                    "bot_key": "test-bot",
                    "bootstrap_secret": "secret", 
                    "auth_endpoint": "http://localhost:8000/v1/auth/token",
                    "client_version": "1.0.0"
                }

            @pytest.fixture
            def mock_session(self):
                return AsyncMock(spec=ClientSession)

            @pytest.mark.asyncio
            async def test_bot_handles_403_forbidden(self, auth_config, mock_session):
                """Test bot handles 403 forbidden (revoked bot) correctly."""

                error_response = {
                    "error_code": "FORBIDDEN",
                    "message": "Bot access has been revoked",
                    "retryable": False
                }

                mock_response = AsyncMock()
                mock_response.status = 403
                mock_response.json = make_mocked_coro(error_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                with pytest.raises(AuthenticationError) as exc_info:
                    await auth_client.obtain_token()

                assert "FORBIDDEN" in str(exc_info.value)
                assert "revoked" in str(exc_info.value)

            @pytest.mark.asyncio
            async def test_bot_handles_426_outdated_client(self, auth_config, mock_session):
                """Test bot handles 426 outdated client version."""

                error_response = {
                    "error_code": "OUTDATED_CLIENT", 
                    "message": "Client version 1.0.0 is too old. Minimum: 2.0.0",
                    "retryable": False
                }

                mock_response = AsyncMock()
                mock_response.status = 426
                mock_response.json = make_mocked_coro(error_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                with pytest.raises(BotClientError) as exc_info:
                    await auth_client.obtain_token()

                assert "OUTDATED_CLIENT" in str(exc_info.value)
                assert "too old" in str(exc_info.value)

            @pytest.mark.asyncio
            async def test_bot_handles_503_service_unavailable(self, auth_config, mock_session):
                """Test bot handles 503 service unavailable."""

                error_response = {
                    "error_code": "TEMPORARY_UNAVAILABLE",
                    "message": "Service temporarily unavailable", 
                    "retryable": True,
                    "backoff_ms": 5000
                }

                mock_response = AsyncMock()
                mock_response.status = 503
                mock_response.json = make_mocked_coro(error_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                with pytest.raises(BotClientError) as exc_info:
                    await auth_client.obtain_token()

                assert "TEMPORARY_UNAVAILABLE" in str(exc_info.value)

            @pytest.mark.asyncio
            async def test_ensure_fresh_token_renews_expired(self, auth_config, mock_session):
                """Test ensure_fresh_token renews expired tokens."""

                success_response = {
                    "access_token": "new-token",
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "issued_at": "2025-08-25T10:30:00Z"
                }

                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = make_mocked_coro(success_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(auth_config, mock_session)

                # Simulate expired token
                auth_client.access_token = "old-token"
                auth_client.expires_at = datetime.utcnow() - timedelta(seconds=1)

                await auth_client.ensure_fresh_token()

                # Should have obtained new token
                assert auth_client.access_token == "new-token"
                assert mock_session.post.called

            @pytest.mark.asyncio
            async def test_client_version_default(self, mock_session):
                """Test client version defaults to 1.0.0 if not specified."""

                config_no_version = {
                    "bot_key": "test-bot",
                    "bootstrap_secret": "secret",
                    "auth_endpoint": "http://localhost:8000/v1/auth/token"
                }

                success_response = {
                    "access_token": "token",
                    "token_type": "Bearer", 
                    "expires_in": 900,
                    "issued_at": "2025-08-25T10:30:00Z"
                }

                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = make_mocked_coro(success_response)
                mock_session.post.return_value.__aenter__.return_value = mock_response

                auth_client = AuthClient(config_no_version, mock_session)
                await auth_client.obtain_token()

                # Should use default version in header
                call_args = mock_session.post.call_args
                assert call_args[1]["headers"]["X-Client-Version"] == "1.0.0"