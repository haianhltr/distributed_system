#!/usr/bin/env python3
"""
Real-world test of the improved bot implementation.
Tests the bot against the actual running distributed system.
"""

import asyncio
import sys
import os
import time
import signal

# Add the bots directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bots'))

from bot import Bot, BotState

class BotTester:
    """Test the improved bot in real scenarios"""
    
    def __init__(self):
        self.test_results = []
    
    def log_result(self, test_name, success, details=""):
        """Log test result"""
        status = "PASS" if success else "FAIL"
        self.test_results.append((test_name, success, details))
        print(f"[{status}] {test_name}: {details}")
    
    async def test_normal_startup(self):
        """Test normal bot startup and registration"""
        print("\n=== Test 1: Normal Startup ===")
        
        # Configure bot for local testing
        os.environ['MAIN_SERVER_URL'] = 'http://localhost:3001'
        os.environ['BOT_ID'] = 'test-improved-bot-1'
        os.environ['PROCESSING_DURATION_MS'] = '5000'  # 5 seconds for testing
        os.environ['HEARTBEAT_INTERVAL_MS'] = '10000'  # 10 seconds
        os.environ['MAX_STARTUP_ATTEMPTS'] = '10'
        
        bot = Bot()
        startup_start = time.time()
        
        try:
            # Mock the job loop to run briefly
            original_job_loop = bot.job_loop
            async def test_job_loop():
                await asyncio.sleep(15)  # Run for 15 seconds
            bot.job_loop = test_job_loop
            
            await bot.start()
            
            startup_time = time.time() - startup_start
            
            # Verify success
            if bot.state == BotState.READY:
                self.log_result("Normal Startup", True, f"Started in {startup_time:.2f}s after {bot.startup_attempts} attempts")
                
                # Check metrics
                metrics = bot.get_metrics()
                self.log_result("Metrics Collection", True, f"Collected {len(metrics)} metric fields")
                
                # Wait a bit to see heartbeats
                await asyncio.sleep(2)
                
                self.log_result("Bot Running", True, f"Bot state: {bot.state.value}")
                
            else:
                self.log_result("Normal Startup", False, f"Bot in state {bot.state.value} instead of READY")
            
        except Exception as e:
            self.log_result("Normal Startup", False, f"Exception: {e}")
        finally:
            await bot.stop()
            self.log_result("Graceful Shutdown", bot.state == BotState.STOPPED, f"Final state: {bot.state.value}")
    
    async def test_server_down_recovery(self):
        """Test bot behavior when server is temporarily down"""
        print("\n=== Test 2: Server Down Recovery ===")
        
        # Configure bot with unreachable server initially
        os.environ['MAIN_SERVER_URL'] = 'http://localhost:9999'  # Wrong port
        os.environ['BOT_ID'] = 'test-improved-bot-2'
        os.environ['MAX_STARTUP_ATTEMPTS'] = '5'
        
        bot = Bot()
        
        try:
            # Try to start (should fail)
            await asyncio.wait_for(bot.start(), timeout=30)
            self.log_result("Server Down Handling", False, "Bot should have failed to start")
        
        except Exception as e:
            # This is expected
            self.log_result("Server Down Handling", True, f"Bot failed gracefully: {type(e).__name__}")
            self.log_result("Retry Attempts", bot.startup_attempts >= 3, f"Made {bot.startup_attempts} attempts")
            
            # Check circuit breaker state
            if bot.registration_breaker.state == "open":
                self.log_result("Circuit Breaker", True, "Registration circuit breaker opened")
            else:
                self.log_result("Circuit Breaker", False, f"Circuit breaker state: {bot.registration_breaker.state}")
        
        finally:
            await bot.stop()
    
    async def test_job_processing(self):
        """Test actual job processing with the real server"""
        print("\n=== Test 3: Job Processing ===")
        
        # Configure for real server
        os.environ['MAIN_SERVER_URL'] = 'http://localhost:3001'
        os.environ['BOT_ID'] = 'test-improved-bot-3'
        os.environ['PROCESSING_DURATION_MS'] = '2000'  # 2 seconds
        os.environ['HEARTBEAT_INTERVAL_MS'] = '5000'   # 5 seconds
        
        bot = Bot()
        job_count = 0
        
        try:
            # Override job completion to count jobs
            original_complete_processing = bot.complete_processing
            async def count_complete_processing(start_time):
                nonlocal job_count
                job_count += 1
                print(f"  Job {job_count} completed")
                await original_complete_processing(start_time)
            bot.complete_processing = count_complete_processing
            
            # Run for limited time
            start_task = asyncio.create_task(bot.start())
            
            # Wait for bot to be ready
            for _ in range(30):  # Wait up to 30 seconds
                if bot.state == BotState.READY:
                    break
                await asyncio.sleep(1)
            
            if bot.state == BotState.READY:
                self.log_result("Job System Ready", True, "Bot reached READY state")
                
                # Let it process a few jobs
                await asyncio.sleep(10)  # Process for 10 seconds
                
                self.log_result("Job Processing", job_count > 0, f"Processed {job_count} jobs")
                
                # Check metrics
                metrics = bot.get_metrics()
                self.log_result("Job Metrics", metrics['total_jobs_processed'] > 0, 
                              f"Total jobs in metrics: {metrics['total_jobs_processed']}")
                
            else:
                self.log_result("Job System Ready", False, f"Bot stuck in state: {bot.state.value}")
            
        except Exception as e:
            self.log_result("Job Processing", False, f"Exception: {e}")
        finally:
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass
            await bot.stop()
    
    async def test_circuit_breaker_integration(self):
        """Test circuit breaker with real network failures"""
        print("\n=== Test 4: Circuit Breaker Integration ===")
        
        os.environ['MAIN_SERVER_URL'] = 'http://localhost:3001'
        os.environ['BOT_ID'] = 'test-improved-bot-4'
        
        bot = Bot()
        
        # Test registration circuit breaker by forcing failures
        registration_failures = 0
        
        original_attempt_registration = bot._attempt_registration
        async def fail_registration():
            nonlocal registration_failures
            registration_failures += 1
            if registration_failures <= 3:
                bot.registration_breaker.record_failure()
                return False
            else:
                return await original_attempt_registration()
        
        bot._attempt_registration = fail_registration
        
        try:
            # Mock job loop
            async def test_job_loop():
                await asyncio.sleep(1)
            bot.job_loop = test_job_loop
            
            await bot.start()
            
            self.log_result("Circuit Breaker Recovery", True, 
                          f"Recovered after {registration_failures} failures")
            
            # Check final circuit breaker state
            if bot.registration_breaker.state == "closed":
                self.log_result("Circuit Breaker Reset", True, "Circuit breaker properly reset")
            else:
                self.log_result("Circuit Breaker Reset", False, 
                              f"Circuit breaker state: {bot.registration_breaker.state}")
            
        except Exception as e:
            self.log_result("Circuit Breaker Integration", False, f"Exception: {e}")
        finally:
            await bot.stop()
    
    async def test_state_machine_robustness(self):
        """Test state machine under various conditions"""
        print("\n=== Test 5: State Machine Robustness ===")
        
        os.environ['MAIN_SERVER_URL'] = 'http://localhost:3001'
        os.environ['BOT_ID'] = 'test-improved-bot-5'
        
        bot = Bot()
        state_changes = []
        
        # Track all state changes
        original_change_state = bot._change_state
        def track_state_change(new_state):
            original_change_state(new_state)
            state_changes.append(new_state)
            print(f"  State: {new_state.value}")
        
        bot._change_state = track_state_change
        
        try:
            # Mock job loop
            async def test_job_loop():
                await asyncio.sleep(2)
            bot.job_loop = test_job_loop
            
            await bot.start()
            
            expected_states = [BotState.REGISTERING, BotState.HEALTH_CHECK, BotState.READY]
            states_found = all(state in state_changes for state in expected_states)
            
            self.log_result("State Transitions", states_found, 
                          f"Followed expected state sequence: {[s.value for s in state_changes]}")
            
            # Test error state handling
            bot._change_state(BotState.ERROR)
            await asyncio.sleep(1)  # Let error handling run
            
            if bot.state != BotState.ERROR:
                self.log_result("Error Recovery", True, f"Recovered from error state to {bot.state.value}")
            else:
                self.log_result("Error Recovery", False, "Stuck in error state")
            
        except Exception as e:
            self.log_result("State Machine Robustness", False, f"Exception: {e}")
        finally:
            await bot.stop()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, success, _ in self.test_results if success)
        total = len(self.test_results)
        
        for test_name, success, details in self.test_results:
            status = "PASS" if success else "FAIL"
            print(f"[{status}] {test_name}")
            if details:
                print(f"      {details}")
        
        print(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            print("\nAll tests passed! The improved bot is PRODUCTION READY.")
        else:
            print(f"\n{total - passed} tests failed. Review and fix issues.")
        
        return passed == total

async def main():
    """Run all real-world tests"""
    print("Improved Bot Real-World Testing")
    print("=" * 60)
    print("Testing against actual distributed system...")
    
    tester = BotTester()
    
    # Run all tests
    try:
        await tester.test_normal_startup()
        await tester.test_server_down_recovery()
        await tester.test_job_processing()
        await tester.test_circuit_breaker_integration()
        await tester.test_state_machine_robustness()
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
    except Exception as e:
        print(f"\nUnexpected error during testing: {e}")
    
    # Print summary
    success = tester.print_summary()
    return success

if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nTesting stopped by user")
        sys.exit(1)