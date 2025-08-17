#!/usr/bin/env python3
"""
Test script to verify real bots can complete jobs successfully
"""
import asyncio
import asyncpg
import httpx
import os
import sys
import time
from datetime import datetime

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ds_user:ds_password@localhost:5432/distributed_system")
API_URL = "http://localhost:3001"
ADMIN_TOKEN = "admin-secret-token"

async def test_real_bot_workflow():
    """Test real bots can complete jobs"""
    print("\n=== Testing Real Bot Job Completion ===\n")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Step 1: Check current system state
        print("1. Checking current system state...")
        
        bot_count = await conn.fetchval("SELECT COUNT(*) FROM bots WHERE status != 'down'")
        pending_jobs = await conn.fetchval("SELECT COUNT(*) FROM jobs WHERE status = 'pending'")
        processing_jobs = await conn.fetchval("SELECT COUNT(*) FROM jobs WHERE status = 'processing'")
        
        print(f"   Active bots: {bot_count}")
        print(f"   Pending jobs: {pending_jobs}")
        print(f"   Processing jobs: {processing_jobs}")
        
        # Step 2: Create a few test jobs
        print("\n2. Creating test jobs...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_URL}/jobs/populate",
                json={"batchSize": 5},
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
            )
            
            if response.status_code == 200:
                jobs_data = response.json()
                created_jobs = [job['id'] for job in jobs_data['jobs']]
                print(f"   [OK] Created {len(created_jobs)} test jobs")
            else:
                print(f"   [ERROR] Failed to create jobs: {response.status_code}")
                return False
        
        # Step 3: Wait for bots to process jobs
        print("\n3. Waiting for bots to process jobs (30 seconds)...")
        
        for i in range(6):  # 30 seconds / 5 second intervals
            await asyncio.sleep(5)
            
            # Check job states
            job_states = await conn.fetch("""
                SELECT status, COUNT(*) as count 
                FROM jobs 
                WHERE id = ANY($1::text[]) 
                GROUP BY status
            """, created_jobs)
            
            states = {row['status']: row['count'] for row in job_states}
            print(f"   Step {i+1}/6 - Job states: {dict(states)}")
            
            # If all jobs are completed (succeeded or failed), break
            remaining = states.get('pending', 0) + states.get('claimed', 0) + states.get('processing', 0)
            if remaining == 0:
                print("   [OK] All jobs completed!")
                break
        
        # Step 4: Analyze results
        print("\n4. Analyzing results...")
        
        final_results = await conn.fetch("""
            SELECT j.id, j.status, j.finished_at, r.result, r.duration_ms, r.processed_by
            FROM jobs j
            LEFT JOIN results r ON j.id = r.job_id
            WHERE j.id = ANY($1::text[])
            ORDER BY j.finished_at
        """, created_jobs)
        
        succeeded_count = 0
        failed_count = 0
        stuck_count = 0
        
        for job in final_results:
            if job['status'] == 'succeeded':
                succeeded_count += 1
                print(f"   [OK] Job {job['id'][:8]} succeeded: result={job['result']}, duration={job['duration_ms']}ms, bot={job['processed_by']}")
            elif job['status'] == 'failed':
                failed_count += 1
                print(f"   [FAIL] Job {job['id'][:8]} failed")
            else:
                stuck_count += 1
                print(f"   [STUCK] Job {job['id'][:8]} stuck in {job['status']} state")
        
        print(f"\n   Summary: {succeeded_count} succeeded, {failed_count} failed, {stuck_count} stuck")
        
        # Step 5: Check if bots are idle and ready for more work
        print("\n5. Checking bot states...")
        
        bot_states = await conn.fetch("""
            SELECT id, status, current_job_id, last_heartbeat_at
            FROM bots 
            WHERE status != 'down'
            ORDER BY id
        """)
        
        idle_bots = 0
        for bot in bot_states:
            last_heartbeat = bot['last_heartbeat_at']
            age_seconds = (datetime.now() - last_heartbeat).total_seconds() if last_heartbeat else float('inf')
            
            if bot['status'] == 'idle' and bot['current_job_id'] is None:
                idle_bots += 1
                print(f"   [OK] Bot {bot['id']} is idle and ready")
            else:
                print(f"   [BUSY] Bot {bot['id']} status={bot['status']}, job={bot['current_job_id']}, heartbeat_age={age_seconds:.1f}s")
        
        print(f"\n   {idle_bots}/{len(bot_states)} bots are idle and ready")
        
        await conn.close()
        
        # Final verdict
        success = (succeeded_count > 0 and stuck_count == 0)
        
        if success:
            print("\n[SUCCESS] Real bots can successfully complete jobs!")
            print("- Job completion endpoints are working")
            print("- Bots can process and submit results")
            print("- Database records are properly updated")
            print("- System is functioning correctly")
        else:
            print("\n[ISSUES DETECTED]:")
            if stuck_count > 0:
                print(f"- {stuck_count} jobs are stuck in processing")
            if succeeded_count == 0:
                print("- No jobs completed successfully")
        
        return success
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing real bot job completion workflow...")
    success = asyncio.run(test_real_bot_workflow())
    sys.exit(0 if success else 1)