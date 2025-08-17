"""Test script for manual job release functionality."""

import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'main_server'))

from database import DatabaseManager
from services.job_release_service import JobReleaseService
import uuid


async def test_manual_job_release():
    """Test manual job release functionality."""
    
    # Initialize services
    db_url = "postgresql://ds_user:ds_password@localhost:5432/distributed_system"
    db_manager = DatabaseManager(db_url)
    job_release_service = JobReleaseService(db_manager)
    
    try:
        await db_manager.initialize()
        print("[OK] Database initialized")
        
        # Create test bot
        test_bot_id = f"test-bot-{uuid.uuid4().hex[:8]}"
        async with db_manager.get_connection() as conn:
            await conn.execute("""
                INSERT INTO bots (id, status, last_heartbeat_at, created_at, health_status)
                VALUES ($1, 'busy', NOW(), NOW(), 'potentially_stuck')
            """, test_bot_id)
        
        # Create test job that's stuck in processing (but won't be auto-recovered)
        test_job_id = f"test-job-{uuid.uuid4().hex[:8]}"
        async with db_manager.get_connection() as conn:
            await conn.execute("""
                INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at, created_at)
                VALUES ($1, 10, 20, 'sum', 'processing', $2, NOW() - INTERVAL '15 minutes', NOW() - INTERVAL '8 minutes', NOW() - INTERVAL '16 minutes')
            """, test_job_id, test_bot_id)
            
            # Update bot to reference this job
            await conn.execute("""
                UPDATE bots SET current_job_id = $1, stuck_job_id = $1 WHERE id = $2
            """, test_job_id, test_bot_id)
        
        print(f"[OK] Created test bot {test_bot_id} with stuck job {test_job_id}")
        
        # Test stuck jobs summary before release
        print("[INFO] Getting stuck jobs summary before release...")
        summary = await job_release_service.get_stuck_jobs_summary()
        print(f"   Processing jobs stuck > 10 min: {summary['summary']['processing_count']}")
        print(f"   Claimed jobs stuck > 5 min: {summary['summary']['claimed_count']}")
        print(f"   Potentially stuck bots: {summary['summary']['stuck_bots_count']}")
        
        # Verify initial state
        async with db_manager.get_connection() as conn:
            initial_state = await conn.fetchrow("""
                SELECT j.status as job_status, b.status as bot_status, b.health_status, b.current_job_id 
                FROM jobs j 
                JOIN bots b ON j.claimed_by = b.id 
                WHERE j.id = $1
            """, test_job_id)
            print(f"[BEFORE] Job: {initial_state['job_status']}, Bot: {initial_state['bot_status']}, Health: {initial_state['health_status']}")
        
        # Test manual job release
        print(f"[TEST] Testing manual job release for job {test_job_id}...")
        release_result = await job_release_service.release_job_from_bot(test_job_id, admin_user="test_admin")
        print(f"[OK] Job release result: {release_result['status']}")
        print(f"     Message: {release_result['message']}")
        
        # Verify job was reset to pending
        async with db_manager.get_connection() as conn:
            final_state = await conn.fetchrow("""
                SELECT j.status as job_status, j.claimed_by, j.error,
                       b.status as bot_status, b.health_status, b.current_job_id
                FROM jobs j 
                LEFT JOIN bots b ON j.claimed_by = b.id 
                WHERE j.id = $1
            """, test_job_id)
            
            print(f"[AFTER] Job: {final_state['job_status']}, claimed_by: {final_state['claimed_by']}")
            print(f"        Error: {final_state['error']}")
            if final_state['bot_status']:
                print(f"        Bot: {final_state['bot_status']}, Health: {final_state['health_status']}")
                print(f"        Bot current_job_id: {final_state['current_job_id']}")
        
        # Test bot restart functionality
        print(f"[TEST] Testing bot restart for bot {test_bot_id}...")
        restart_result = await job_release_service.restart_bot(test_bot_id, admin_user="test_admin")
        print(f"[OK] Bot restart result: {restart_result['status']}")
        print(f"     Message: {restart_result['message']}")
        
        # Verify bot status after restart
        async with db_manager.get_connection() as conn:
            bot_final_state = await conn.fetchrow("""
                SELECT status, health_status, current_job_id FROM bots WHERE id = $1
            """, test_bot_id)
            print(f"[FINAL] Bot status: {bot_final_state['status']}, Health: {bot_final_state['health_status']}")
            print(f"        Current job: {bot_final_state['current_job_id']}")
        
        # Test stuck jobs summary after operations
        print("[INFO] Getting stuck jobs summary after operations...")
        final_summary = await job_release_service.get_stuck_jobs_summary()
        print(f"   Processing jobs stuck > 10 min: {final_summary['summary']['processing_count']}")
        print(f"   Potentially stuck bots: {final_summary['summary']['stuck_bots_count']}")
        
        print("[OK] All manual release tests completed successfully!")
        
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
        except Exception as e:
            print(f"[CLEANUP] Cleanup warning: {e}")
        
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(test_manual_job_release())