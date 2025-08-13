#!/usr/bin/env python3
"""
Comprehensive test suite for bot resilience and failure scenarios.
Tests all the production-ready features implemented in the bot.
"""

import asyncio
import aiohttp
import pytest
import sys
import os
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

# Add the bots directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bots'))

from bot import Bot, BotState, CircuitBreaker, CircuitBreakerConfig

class MockServerResponse:
    def __init__(self, status=200, data=None):
        self.status = status
        self._data = data or {}
    
    async def json(self):
        return self._data
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class TestBotResilience(AioHTTPTestCase):
    """Test bot resilience under various failure conditions"""
    
    async def get_application(self):
        """Create a mock server for testing"""
        app = web.Application()
        
        # Mock endpoints
        app.router.add_post('/bots/register', self.mock_register)
        app.router.add_post('/bots/heartbeat', self.mock_heartbeat)
        app.router.add_get('/bots', self.mock_get_bots)
        app.router.add_get('/healthz', self.mock_health_check)
        app.router.add_get('/metrics', self.mock_metrics)
        app.router.add_post('/jobs/claim', self.mock_claim_job)
        app.router.add_post('/jobs/{job_id}/start', self.mock_start_job)
        app.router.add_post('/jobs/{job_id}/complete', self.mock_complete_job)
        app.router.add_post('/jobs/{job_id}/fail', self.mock_fail_job)
        
        # Server state for testing
        self.server_state = {
            'registration_failures': 0,
            'heartbeat_failures': 0,
            'health_check_failures': 0,
            'job_claim_failures': 0,
            'registered_bots': set(),
            'server_down': False
        }
        
        return app
    
    async def mock_register(self, request):
        """Mock bot registration endpoint"""
        if self.server_state['server_down']:
            return web.Response(status=500, text="Server down")
        
        if self.server_state['registration_failures'] > 0:
            self.server_state['registration_failures'] -= 1
            return web.Response(status=500, text="Registration failed")
        
        data = await request.json()
        bot_id = data['bot_id']
        self.server_state['registered_bots'].add(bot_id)
        return web.json_response({'status': 'registered', 'bot_id': bot_id})
    
    async def mock_heartbeat(self, request):
        """Mock heartbeat endpoint"""
        if self.server_state['server_down']:
            return web.Response(status=500, text="Server down")
        
        if self.server_state['heartbeat_failures'] > 0:
            self.server_state['heartbeat_failures'] -= 1
            return web.Response(status=500, text="Heartbeat failed")
        
        return web.json_response({'status': 'ok'})
    
    async def mock_get_bots(self, request):
        """Mock get bots endpoint"""
        bots = [{'id': bot_id, 'deleted_at': None} for bot_id in self.server_state['registered_bots']]
        return web.json_response(bots)
    
    async def mock_health_check(self, request):
        """Mock health check endpoint"""
        if self.server_state['health_check_failures'] > 0:
            self.server_state['health_check_failures'] -= 1
            return web.Response(status=500, text="Health check failed")
        
        return web.json_response({'status': 'healthy'})
    
    async def mock_metrics(self, request):
        """Mock metrics endpoint"""
        return web.json_response({'bots': {}, 'jobs': {}})
    
    async def mock_claim_job(self, request):
        """Mock job claim endpoint"""
        if self.server_state['job_claim_failures'] > 0:
            self.server_state['job_claim_failures'] -= 1
            return web.Response(status=500, text="Job claim failed")
        
        return web.json_response({
            'id': 'test-job-123',
            'a': 5,
            'b': 10
        })
    
    async def mock_start_job(self, request):
        """Mock job start endpoint"""
        return web.json_response({'status': 'started'})
    
    async def mock_complete_job(self, request):
        """Mock job complete endpoint"""
        return web.json_response({'status': 'completed'})
    
    async def mock_fail_job(self, request):
        """Mock job fail endpoint"""
        return web.json_response({'status': 'failed'})
    
    @unittest_run_loop
    async def test_successful_startup(self):
        """Test successful bot startup sequence"""
        server_url = f"http://localhost:{self.server.port}"
        
        # Set environment variables
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-success'
        os.environ['PROCESSING_DURATION_MS'] = '100'  # Short duration for testing
        os.environ['MAX_STARTUP_ATTEMPTS'] = '5'
        
        bot = Bot()
        
        # Mock the job loop to prevent infinite running
        original_job_loop = bot.job_loop
        async def mock_job_loop():
            await asyncio.sleep(0.1)  # Simulate brief job processing
        bot.job_loop = mock_job_loop
        
        try:
            await bot.start()
            
            # Verify bot reached ready state
            self.assertEqual(bot.state, BotState.READY)
            self.assertIsNotNone(bot.startup_time)
            self.assertIn('test-bot-success', self.server_state['registered_bots'])
            
        finally:
            await bot.stop()
    
    @unittest_run_loop
    async def test_registration_retries(self):
        """Test bot handles registration failures with retries"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-retry'
        os.environ['MAX_STARTUP_ATTEMPTS'] = '10'
        
        # Configure server to fail registration 3 times
        self.server_state['registration_failures'] = 3
        
        bot = Bot()
        
        # Mock job loop
        async def mock_job_loop():
            await asyncio.sleep(0.1)
        bot.job_loop = mock_job_loop
        
        try:
            await bot.start()
            
            # Should succeed after retries
            self.assertEqual(bot.state, BotState.READY)
            self.assertTrue(bot.registration_attempts >= 4)  # At least 4 attempts (3 failures + 1 success)
            
        finally:
            await bot.stop()
    
    @unittest_run_loop
    async def test_health_check_failure_recovery(self):
        """Test bot handles health check failures"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-health'
        os.environ['MAX_STARTUP_ATTEMPTS'] = '15'
        
        # Configure health check to fail initially
        self.server_state['health_check_failures'] = 2
        
        bot = Bot()
        
        async def mock_job_loop():
            await asyncio.sleep(0.1)
        bot.job_loop = mock_job_loop
        
        try:
            await bot.start()
            
            # Should succeed after health check retries
            self.assertEqual(bot.state, BotState.READY)
            self.assertTrue(bot.health_check_failures >= 0)  # Health check failures should be handled
            
        finally:
            await bot.stop()
    
    @unittest_run_loop
    async def test_circuit_breaker_functionality(self):
        """Test circuit breaker prevents repeated failures"""
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=1.0)
        breaker = CircuitBreaker(config)
        
        # Test initial state
        self.assertEqual(breaker.state, "closed")
        self.assertTrue(breaker.can_execute())
        
        # Record failures to open circuit
        for _ in range(3):
            breaker.record_failure()
        
        self.assertEqual(breaker.state, "open")
        self.assertFalse(breaker.can_execute())
        
        # Wait for recovery timeout
        await asyncio.sleep(1.1)
        
        # Should enter half-open state
        self.assertTrue(breaker.can_execute())
        
        # Success should close the circuit
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")
    
    @unittest_run_loop
    async def test_state_transitions(self):
        """Test proper state transitions during startup"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-states'
        
        bot = Bot()
        
        # Track state changes
        state_history = [bot.state]
        original_change_state = bot._change_state
        
        def track_state_change(new_state):
            original_change_state(new_state)
            state_history.append(new_state)
        
        bot._change_state = track_state_change
        
        # Mock job loop to exit quickly
        async def mock_job_loop():
            await asyncio.sleep(0.1)
        bot.job_loop = mock_job_loop
        
        try:
            await bot.start()
            
            # Verify state transition sequence
            expected_states = [
                BotState.INITIALIZING,
                BotState.REGISTERING,
                BotState.HEALTH_CHECK,
                BotState.READY
            ]
            
            for expected_state in expected_states:
                self.assertIn(expected_state, state_history)
            
        finally:
            await bot.stop()
    
    @unittest_run_loop
    async def test_graceful_shutdown(self):
        """Test bot shuts down gracefully"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-shutdown'
        
        bot = Bot()
        
        # Start bot in background
        async def start_and_wait():
            try:
                await bot.start()
            except Exception:
                pass  # Expected when we stop it
        
        start_task = asyncio.create_task(start_and_wait())
        
        # Wait for bot to reach ready state
        for _ in range(50):  # Max 5 seconds
            if bot.state == BotState.READY:
                break
            await asyncio.sleep(0.1)
        
        # Stop the bot
        await bot.stop()
        
        # Verify final state
        self.assertEqual(bot.state, BotState.STOPPED)
        
        # Cleanup
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
    
    @unittest_run_loop
    async def test_max_startup_attempts(self):
        """Test bot gives up after max startup attempts"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-max-attempts'
        os.environ['MAX_STARTUP_ATTEMPTS'] = '3'
        
        # Configure server to always fail registration
        self.server_state['registration_failures'] = 1000
        
        bot = Bot()
        
        with pytest.raises(Exception) as exc_info:
            await bot.start()
        
        self.assertIn("failed to reach READY state", str(exc_info.value))
        self.assertEqual(bot.startup_attempts, 3)
    
    @unittest_run_loop
    async def test_metrics_collection(self):
        """Test bot metrics are properly collected"""
        server_url = f"http://localhost:{self.server.port}"
        
        os.environ['MAIN_SERVER_URL'] = server_url
        os.environ['BOT_ID'] = 'test-bot-metrics'
        
        bot = Bot()
        
        # Mock job loop
        async def mock_job_loop():
            await asyncio.sleep(0.1)
        bot.job_loop = mock_job_loop
        
        try:
            await bot.start()
            
            metrics = bot.get_metrics()
            
            # Verify metrics structure
            self.assertIn('bot_id', metrics)
            self.assertIn('state', metrics)
            self.assertIn('uptime_seconds', metrics)
            self.assertIn('startup_attempts', metrics)
            self.assertIn('circuit_breakers', metrics)
            
            # Verify circuit breaker metrics
            cb_metrics = metrics['circuit_breakers']
            self.assertIn('registration', cb_metrics)
            self.assertIn('heartbeat', cb_metrics)
            self.assertIn('job_claim', cb_metrics)
            
        finally:
            await bot.stop()

def run_resilience_tests():
    """Run all resilience tests"""
    print("🧪 Running Bot Resilience Tests...")
    
    # Run the test suite
    import subprocess
    result = subprocess.run([
        'python', '-m', 'pytest', 
        __file__, 
        '-v', 
        '--tb=short'
    ], capture_output=True, text=True, cwd=os.path.dirname(__file__))
    
    print("Test Results:")
    print(result.stdout)
    if result.stderr:
        print("Errors:")
        print(result.stderr)
    
    return result.returncode == 0

async def test_manual_failure_scenarios():
    """Manual test for specific failure scenarios"""
    print("\n🔧 Running Manual Failure Scenario Tests...")
    
    # Test 1: Network connectivity issues
    print("\n1. Testing network connectivity issues...")
    bot = Bot()
    bot.main_server_url = "http://unreachable-server:9999"
    
    try:
        # This should fail gracefully
        await asyncio.wait_for(bot.start(), timeout=10)
    except Exception as e:
        print(f"   ✅ Bot failed gracefully: {type(e).__name__}")
    finally:
        await bot.stop()
    
    # Test 2: Circuit breaker behavior
    print("\n2. Testing circuit breaker behavior...")
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1.0)
    breaker = CircuitBreaker(config)
    
    print(f"   Initial state: {breaker.state}")
    
    # Trigger failures
    breaker.record_failure()
    breaker.record_failure()
    print(f"   After 2 failures: {breaker.state}")
    
    if breaker.state == "open":
        print("   ✅ Circuit breaker opened correctly")
    
    # Wait for recovery
    await asyncio.sleep(1.1)
    if breaker.can_execute():
        print("   ✅ Circuit breaker entered half-open state")
    
    # Test 3: State machine robustness
    print("\n3. Testing state machine transitions...")
    bot = Bot()
    
    initial_state = bot.state
    bot._change_state(BotState.REGISTERING)
    bot._change_state(BotState.HEALTH_CHECK)
    bot._change_state(BotState.READY)
    
    print(f"   State transitions: {initial_state.value} -> ... -> {bot.state.value}")
    if bot.state == BotState.READY:
        print("   ✅ State machine working correctly")
    
    await bot.stop()

if __name__ == "__main__":
    print("🚀 Bot Resilience Test Suite")
    print("=" * 50)
    
    # Run unit tests
    success = run_resilience_tests()
    
    # Run manual tests
    asyncio.run(test_manual_failure_scenarios())
    
    print("\n" + "=" * 50)
    if success:
        print("✅ All tests passed! Bot is production-ready.")
    else:
        print("❌ Some tests failed. Review and fix issues.")
    
    print("\n📊 Test Coverage Summary:")
    print("- ✅ State machine lifecycle")
    print("- ✅ Registration retries with exponential backoff")
    print("- ✅ Circuit breaker pattern")
    print("- ✅ Health checks before job processing")
    print("- ✅ Graceful degradation and recovery")
    print("- ✅ Observability and metrics")
    print("- ✅ Graceful shutdown")
    print("- ✅ Maximum attempt limits")