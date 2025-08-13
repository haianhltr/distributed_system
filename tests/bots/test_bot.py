import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import sys
import os

# Add bots directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bots'))

from bot import Bot


@pytest.fixture
def bot_config():
    """Bot configuration for testing"""
    return {
        "bot_id": "test-bot-123",
        "main_server_url": "http://localhost:3001",
        "heartbeat_interval_ms": 1000,
        "processing_duration_ms": 2000,
        "failure_rate": 0.1
    }


@pytest.fixture
def mock_http_client():
    """Mock HTTP client"""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.mark.asyncio
class TestBotInitialization:
    """Test bot initialization and configuration"""
    
    async def test_bot_creation(self, bot_config):
        """Test bot can be created with config"""
        bot = Bot(
            bot_id=bot_config["bot_id"],
            main_server_url=bot_config["main_server_url"],
            heartbeat_interval_ms=bot_config["heartbeat_interval_ms"],
            processing_duration_ms=bot_config["processing_duration_ms"],
            failure_rate=bot_config["failure_rate"]
        )
        
        assert bot.bot_id == bot_config["bot_id"]
        assert bot.main_server_url == bot_config["main_server_url"]
        assert bot.heartbeat_interval_ms == bot_config["heartbeat_interval_ms"]
        assert bot.processing_duration_ms == bot_config["processing_duration_ms"]
        assert bot.failure_rate == bot_config["failure_rate"]
        assert not bot.shutdown_requested
    
    async def test_bot_with_default_config(self):
        """Test bot creation with minimal config"""
        bot = Bot(
            bot_id="test-bot",
            main_server_url="http://localhost:3001"
        )
        
        assert bot.heartbeat_interval_ms == 30000  # Default value
        assert bot.processing_duration_ms == 60000  # Default value
        assert bot.failure_rate == 0.1  # Default value


@pytest.mark.asyncio
class TestBotRegistration:
    """Test bot registration with main server"""
    
    async def test_successful_registration(self, bot_config, mock_http_client):
        """Test successful bot registration"""
        # Mock successful registration response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"bot_id": bot_config["bot_id"], "status": "registered"}
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.register()
            
        assert result is True
        mock_http_client.post.assert_called_once_with(
            f"{bot_config['main_server_url']}/bots/register",
            json={"bot_id": bot_config["bot_id"]}
        )
    
    async def test_registration_failure(self, bot_config, mock_http_client):
        """Test bot registration failure"""
        # Mock failed registration response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.register()
            
        assert result is False
    
    async def test_registration_network_error(self, bot_config, mock_http_client):
        """Test bot registration with network error"""
        mock_http_client.post.side_effect = httpx.RequestError("Network error")
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.register()
            
        assert result is False


@pytest.mark.asyncio
class TestJobClaiming:
    """Test job claiming functionality"""
    
    async def test_successful_job_claim(self, bot_config, mock_http_client):
        """Test successful job claiming"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "job-123",
            "a": 10,
            "b": 20,
            "status": "claimed"
        }
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            job = await bot.claim_job()
            
        assert job is not None
        assert job["id"] == "job-123"
        assert job["a"] == 10
        assert job["b"] == 20
        mock_http_client.post.assert_called_once_with(
            f"{bot_config['main_server_url']}/jobs/claim",
            json={"bot_id": bot_config["bot_id"]}
        )
    
    async def test_no_available_jobs(self, bot_config, mock_http_client):
        """Test when no jobs are available"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            job = await bot.claim_job()
            
        assert job is None
    
    async def test_job_claim_error(self, bot_config, mock_http_client):
        """Test job claiming error"""
        mock_http_client.post.side_effect = httpx.RequestError("Server error")
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            job = await bot.claim_job()
            
        assert job is None


@pytest.mark.asyncio
class TestJobProcessing:
    """Test job processing functionality"""
    
    async def test_successful_job_processing(self, bot_config, mock_http_client):
        """Test successful job processing"""
        job = {"id": "job-123", "a": 10, "b": 20}
        
        # Mock successful start and complete responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        bot.processing_duration_ms = 100  # Speed up test
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            with patch('asyncio.sleep'):  # Mock sleep to speed up test
                result = await bot.process_job(job)
        
        assert result is True
        
        # Verify start and complete calls
        assert mock_http_client.post.call_count == 2
        
        # Check start call
        start_call = mock_http_client.post.call_args_list[0]
        assert f"/jobs/{job['id']}/start" in start_call[0][0]
        
        # Check complete call
        complete_call = mock_http_client.post.call_args_list[1]
        assert f"/jobs/{job['id']}/complete" in complete_call[0][0]
        complete_data = complete_call[1]["json"]
        assert complete_data["bot_id"] == bot_config["bot_id"]
        assert complete_data["sum"] == 30  # 10 + 20
    
    async def test_job_processing_with_failure(self, bot_config, mock_http_client):
        """Test job processing with simulated failure"""
        job = {"id": "job-123", "a": 10, "b": 20}
        
        # Mock successful start response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        bot.failure_rate = 1.0  # Force failure
        bot.processing_duration_ms = 100  # Speed up test
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            with patch('asyncio.sleep'):  # Mock sleep to speed up test
                result = await bot.process_job(job)
        
        assert result is False
        
        # Verify start and fail calls
        assert mock_http_client.post.call_count == 2
        
        # Check fail call
        fail_call = mock_http_client.post.call_args_list[1]
        assert f"/jobs/{job['id']}/fail" in fail_call[0][0]
    
    async def test_job_start_failure(self, bot_config, mock_http_client):
        """Test job processing when start fails"""
        job = {"id": "job-123", "a": 10, "b": 20}
        
        # Mock failed start response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.process_job(job)
        
        assert result is False
        # Should only have one call (start), no complete/fail
        assert mock_http_client.post.call_count == 1


@pytest.mark.asyncio
class TestHeartbeat:
    """Test heartbeat functionality"""
    
    async def test_successful_heartbeat(self, bot_config, mock_http_client):
        """Test successful heartbeat"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"bot_id": bot_config["bot_id"], "status": "heartbeat_received"}
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.send_heartbeat()
        
        assert result is True
        mock_http_client.post.assert_called_once_with(
            f"{bot_config['main_server_url']}/bots/heartbeat",
            json={"bot_id": bot_config["bot_id"]}
        )
    
    async def test_heartbeat_failure(self, bot_config, mock_http_client):
        """Test heartbeat failure"""
        mock_http_client.post.side_effect = httpx.RequestError("Network error")
        
        bot = Bot(**bot_config)
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            result = await bot.send_heartbeat()
        
        assert result is False


@pytest.mark.asyncio
class TestBotLifecycle:
    """Test complete bot lifecycle"""
    
    async def test_bot_lifecycle_with_shutdown(self, bot_config, mock_http_client):
        """Test bot runs and handles shutdown gracefully"""
        # Mock all HTTP responses as successful
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_http_client.post.return_value = mock_response
        
        bot = Bot(**bot_config)
        bot.heartbeat_interval_ms = 100  # Speed up test
        
        # Start bot in background
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            bot_task = asyncio.create_task(bot.run())
            
            # Let it run briefly
            await asyncio.sleep(0.2)
            
            # Request shutdown
            bot.request_shutdown()
            
            # Wait for shutdown
            await bot_task
        
        assert bot.shutdown_requested
        # Should have at least registered and sent heartbeat
        assert mock_http_client.post.call_count >= 2
    
    @patch('signal.signal')
    async def test_bot_signal_handlers(self, mock_signal, bot_config):
        """Test bot sets up signal handlers correctly"""
        bot = Bot(**bot_config)
        
        with patch('asyncio.run'):
            bot.main()
        
        # Verify signal handlers were set up
        assert mock_signal.call_count >= 2  # SIGTERM and SIGINT


@pytest.mark.asyncio
class TestBotErrorHandling:
    """Test bot error handling and resilience"""
    
    async def test_bot_continues_after_claim_error(self, bot_config, mock_http_client):
        """Test bot continues running after job claim errors"""
        # Mock registration success, then claim failures
        responses = [
            MagicMock(status_code=200, json=lambda: {"status": "registered"}),  # register
            MagicMock(status_code=500),  # claim failure
            MagicMock(status_code=200, json=lambda: {"status": "heartbeat_received"}),  # heartbeat
        ]
        mock_http_client.post.side_effect = responses
        
        bot = Bot(**bot_config)
        bot.heartbeat_interval_ms = 100
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            # Run briefly and shutdown
            bot_task = asyncio.create_task(bot.run())
            await asyncio.sleep(0.15)
            bot.request_shutdown()
            await bot_task
        
        # Bot should have made multiple calls despite claim failure
        assert mock_http_client.post.call_count >= 2
    
    async def test_bot_handles_network_interruption(self, bot_config, mock_http_client):
        """Test bot handles network interruptions gracefully"""
        # Simulate network issues
        mock_http_client.post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"status": "registered"}),  # successful register
            httpx.RequestError("Network error"),  # network error
            MagicMock(status_code=200, json=lambda: {"status": "heartbeat_received"}),  # recovery
        ]
        
        bot = Bot(**bot_config)
        bot.heartbeat_interval_ms = 50
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            bot_task = asyncio.create_task(bot.run())
            await asyncio.sleep(0.12)
            bot.request_shutdown()
            await bot_task
        
        # Bot should continue despite network error
        assert not bot.shutdown_requested or mock_http_client.post.call_count >= 3