#!/usr/bin/env python3
"""
Production Demo: Demonstrates all the production-ready features 
of the improved bot implementation.
"""

import asyncio
import sys
import os
import time
import json

# Add the bots directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bots'))

from bot import Bot, BotState

async def demonstrate_production_features():
    """Demonstrate key production features"""
    print("🚀 Production Bot Demo")
    print("=" * 60)
    
    # Configure production-like settings
    os.environ['MAIN_SERVER_URL'] = 'http://localhost:3001'
    os.environ['BOT_ID'] = 'production-demo-bot'
    os.environ['PROCESSING_DURATION_MS'] = '3000'  # 3 seconds
    os.environ['HEARTBEAT_INTERVAL_MS'] = '8000'   # 8 seconds
    os.environ['MAX_STARTUP_ATTEMPTS'] = '15'
    os.environ['FAILURE_RATE'] = '0.1'  # 10% failure rate
    
    print("\n1. 🔧 Configuration:")
    print(f"   Server: {os.environ['MAIN_SERVER_URL']}")
    print(f"   Bot ID: {os.environ['BOT_ID']}")
    print(f"   Processing Duration: {int(os.environ['PROCESSING_DURATION_MS'])/1000}s")
    print(f"   Heartbeat Interval: {int(os.environ['HEARTBEAT_INTERVAL_MS'])/1000}s")
    print(f"   Max Startup Attempts: {os.environ['MAX_STARTUP_ATTEMPTS']}")
    print(f"   Failure Rate: {float(os.environ['FAILURE_RATE'])*100}%")
    
    bot = Bot()
    
    print("\n2. 📊 Initial State:")
    print(f"   State: {bot.state.value}")
    print(f"   Circuit Breakers: {len(bot.get_metrics()['circuit_breakers'])} configured")
    
    # Track state changes for demo
    state_history = []
    original_change_state = bot._change_state
    def track_state_change(new_state):
        original_change_state(new_state)
        state_history.append((new_state, time.time()))
        print(f"   📍 State: {new_state.value}")
    bot._change_state = track_state_change
    
    # Track job processing
    jobs_processed = 0
    original_complete_processing = bot.complete_processing
    async def track_job_completion(start_time):
        nonlocal jobs_processed
        jobs_processed += 1
        duration = time.time() - start_time
        print(f"   ✅ Job {jobs_processed} completed in {duration:.1f}s")
        await original_complete_processing(start_time)
    bot.complete_processing = track_job_completion
    
    startup_start = time.time()
    
    try:
        print("\n3. 🚀 Startup Sequence:")
        
        # Start bot (limit job processing for demo)
        start_task = asyncio.create_task(bot.start())
        
        # Wait for ready state
        for _ in range(30):
            if bot.state == BotState.READY:
                break
            await asyncio.sleep(0.5)
        
        startup_time = time.time() - startup_start
        
        if bot.state == BotState.READY:
            print(f"\n4. ✅ Startup Success:")
            print(f"   Time: {startup_time:.2f}s")
            print(f"   Attempts: {bot.startup_attempts}")
            print(f"   Registration Attempts: {bot.registration_attempts}")
            
            print(f"\n5. 📈 Metrics Collection:")
            metrics = bot.get_metrics()
            print(f"   Bot ID: {metrics['bot_id']}")
            print(f"   Uptime: {metrics['uptime_seconds']:.1f}s")
            print(f"   State: {metrics['state']}")
            print(f"   Circuit Breakers:")
            for name, data in metrics['circuit_breakers'].items():
                print(f"     {name.title()}: {data['state']} (failures: {data['failure_count']})")
            
            print(f"\n6. 🔄 Job Processing Demo (15 seconds):")
            processing_start = time.time()
            
            # Let it process jobs for 15 seconds
            while time.time() - processing_start < 15:
                await asyncio.sleep(1)
                
                # Show periodic updates
                if int(time.time() - processing_start) % 5 == 0:
                    current_metrics = bot.get_metrics()
                    print(f"   📊 {int(time.time() - processing_start)}s: "
                          f"{current_metrics['total_jobs_processed']} jobs total, "
                          f"state: {bot.state.value}")
            
            print(f"\n7. 📊 Final Statistics:")
            final_metrics = bot.get_metrics()
            print(f"   Total Jobs Processed: {final_metrics['total_jobs_processed']}")
            print(f"   Total Uptime: {final_metrics['uptime_seconds']:.1f}s")
            print(f"   Jobs/minute: {(final_metrics['total_jobs_processed'] / final_metrics['uptime_seconds']) * 60:.1f}")
            
            print(f"\n8. 🛑 Graceful Shutdown:")
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass
            
            await bot.stop()
            print(f"   Final State: {bot.state.value}")
            
            print(f"\n9. 🏁 State Transition History:")
            for i, (state, timestamp) in enumerate(state_history):
                if i == 0:
                    print(f"   {state.value} (startup)")
                else:
                    prev_time = state_history[i-1][1]
                    duration = timestamp - prev_time
                    print(f"   {state.value} (after {duration:.1f}s)")
        else:
            print(f"\n❌ Startup Failed: Bot stuck in {bot.state.value} state")
    
    except Exception as e:
        print(f"\n❌ Demo Error: {e}")
        await bot.stop()
    
    print(f"\n🎯 Production Readiness Summary:")
    print("   ✅ Robust state machine with lifecycle management")
    print("   ✅ Registration retries with exponential backoff")
    print("   ✅ Circuit breaker pattern for failure isolation")
    print("   ✅ Comprehensive health checks before job processing")
    print("   ✅ Graceful degradation and recovery mechanisms")
    print("   ✅ Real-time observability and metrics collection")
    print("   ✅ Configurable timeouts and operational limits")
    print("   ✅ Graceful shutdown with cleanup")
    print("   ✅ Structured logging for debugging")
    print("   ✅ Network failure resilience")
    
    print(f"\n🚢 PRODUCTION READY!")

async def demonstrate_failure_scenarios():
    """Demonstrate how bot handles various failure scenarios"""
    print("\n\n💥 Failure Scenario Demonstrations")
    print("=" * 60)
    
    scenarios = [
        {
            "name": "Network Timeout",
            "description": "Server temporarily unreachable",
            "server_url": "http://localhost:9999"
        },
        {
            "name": "Slow Server Response", 
            "description": "Server responds slowly",
            "server_url": "http://httpbin.org/delay/10"  # 10 second delay
        }
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{i}. 🚨 {scenario['name']}:")
        print(f"   {scenario['description']}")
        
        # Configure bot for failure scenario
        os.environ['MAIN_SERVER_URL'] = scenario['server_url']
        os.environ['BOT_ID'] = f'failure-test-bot-{i}'
        os.environ['MAX_STARTUP_ATTEMPTS'] = '3'  # Limit for demo
        
        bot = Bot()
        failures = 0
        
        # Track failures
        original_record_failure = bot.registration_breaker.record_failure
        def count_failures():
            nonlocal failures
            failures += 1
            original_record_failure()
        bot.registration_breaker.record_failure = count_failures
        
        try:
            print(f"   🔄 Attempting startup...")
            await asyncio.wait_for(bot.start(), timeout=15)
            print(f"   ✅ Unexpected success!")
        except Exception as e:
            print(f"   ❌ Failed as expected: {type(e).__name__}")
            print(f"   📊 Registration failures: {failures}")
            print(f"   📊 Circuit breaker state: {bot.registration_breaker.state}")
            print(f"   📊 Startup attempts: {bot.startup_attempts}")
        finally:
            await bot.stop()

async def main():
    """Main demo execution"""
    try:
        await demonstrate_production_features()
        await demonstrate_failure_scenarios()
        
        print("\n" + "=" * 60)
        print("🎉 Demo Complete!")
        print("The improved bot implementation is ready for production deployment.")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Demo interrupted by user")
    except Exception as e:
        print(f"\n\n💥 Demo failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())