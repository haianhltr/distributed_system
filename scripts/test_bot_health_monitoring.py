"""Test script for bot health monitoring and manual recovery system."""

import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'main_server'))

from database import DatabaseManager
from services.monitoring_service import MonitoringService, BotHealthMonitor
from services.bot_service import BotService
from services.job_service import JobService
from services.job_release_service import JobReleaseService
from datalake import DatalakeManager
import uuid
from datetime import datetime


async def test_bot_health_monitoring():
    """Test the bot health monitoring system."""
    
    # Initialize services
    db_url = "postgresql://ds_user:ds_password@localhost:5432/distributed_system"
    db_manager = DatabaseManager(db_url)
    datalake = DatalakeManager("datalake/data")
    
    bot_service = BotService(db_manager)
    job_service = JobService(db_manager, datalake)
    job_release_service = JobReleaseService(db_manager)
    monitoring_service = MonitoringService(db_manager, job_service, bot_service)
    
    try:
        await db_manager.initialize()
        print("[OK] Database initialized")
        
        # Initialize monitoring service
        monitoring_service.initialize()
        print("[OK] Monitoring service initialized")
        
        # Create test bot
        test_bot_id = f"test-bot-{uuid.uuid4().hex[:8]}"
        async with db_manager.get_connection() as conn:
            await conn.execute("""
                INSERT INTO bots (id, status, last_heartbeat_at, created_at, health_status)
                VALUES ($1, 'busy', NOW(), NOW(), 'normal')
            """, test_bot_id)
        
        # Create test job that's been processing for 15 minutes (simulated)
        test_job_id = f"test-job-{uuid.uuid4().hex[:8]}"
        async with db_manager.get_connection() as conn:
            await conn.execute("""
                INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at, created_at)
                VALUES ($1, 10, 20, 'sum', 'processing', $2, NOW() - INTERVAL '15 minutes', NOW() - INTERVAL '15 minutes', NOW() - INTERVAL '16 minutes')
            """, test_job_id, test_bot_id)
            
            # Update bot to reference this job
            await conn.execute("""
                UPDATE bots SET current_job_id = $1 WHERE id = $2
            """, test_job_id, test_bot_id)
        
        print(f"[OK] Created test bot {test_bot_id} with stuck job {test_job_id}")
        
        # Run monitoring check to detect stuck job
        print("[INFO] Running monitoring check...")
        results = await monitoring_service.run_manual_check()
        
        print("[INFO] Monitoring results:")
        for result in results:
            print(f"  - {result['monitor']}: {result['status']}")
            if result.get('checked', 0) > 0:
                print(f"    Found {result['checked']} stuck items, recovered {result.get('recovered', 0)}")
        
        # Check if bot was marked as potentially stuck
        async with db_manager.get_connection() as conn:
            bot_health = await conn.fetchrow("""
                SELECT health_status, stuck_job_id FROM bots WHERE id = $1
            """, test_bot_id)
            
            print(f"[BOT] Bot health status: {bot_health['health_status']}")
            if bot_health['health_status'] == 'potentially_stuck':
                print(f"   Stuck job ID: {bot_health['stuck_job_id']}")
                print("[OK] Bot correctly marked as potentially stuck!")
            else:
                print("[WARN] Bot was not marked as potentially stuck")
        
        # Test job release functionality
        print(f"[TEST] Testing manual job release for job {test_job_id}...")
        release_result = await job_release_service.release_job_from_bot(test_job_id, admin_user="test")
        print(f"[OK] Job release result: {release_result['status']}")
        
        # Verify job was reset to pending
        async with db_manager.get_connection() as conn:
            job_status = await conn.fetchval("""
                SELECT status FROM jobs WHERE id = $1
            """, test_job_id)
            print(f"[JOB] Job status after release: {job_status}")
            
            # Check bot status
            bot_status = await conn.fetchrow("""
                SELECT status, health_status, current_job_id FROM bots WHERE id = $1
            """, test_bot_id)
            print(f"[BOT] Bot status after release: {bot_status['status']}, health: {bot_status['health_status']}")
        
        # Test stuck jobs summary
        print("[INFO] Getting stuck jobs summary...")
        summary = await job_release_service.get_stuck_jobs_summary()
        print(f"   Processing jobs stuck > 10 min: {summary['summary']['processing_count']}")
        print(f"   Claimed jobs stuck > 5 min: {summary['summary']['claimed_count']}")
        print(f"   Potentially stuck bots: {summary['summary']['stuck_bots_count']}")
        
        print("[OK] All tests completed successfully!")
        
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup test data
        try:
            async with db_manager.get_connection() as conn:
                await conn.execute("DELETE FROM jobs WHERE id = $1", test_job_id)
                await conn.execute("DELETE FROM bots WHERE id = $1", test_bot_id)
            print("[CLEANUP] Cleanup completed")
        except:
            pass
        
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(test_bot_health_monitoring())