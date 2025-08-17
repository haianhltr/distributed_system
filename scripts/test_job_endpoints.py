#!/usr/bin/env python3
"""
Test script to verify job completion endpoints are working
"""
import asyncio
import asyncpg
import httpx
import os
import sys
from datetime import datetime

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ds_user:ds_password@localhost:5432/distributed_system")
API_URL = "http://localhost:3001"

async def test_job_endpoints():
    """Test the job completion and failure endpoints"""
    print("\n=== Testing Job Completion Endpoints ===\n")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Step 1: Create a test job and bot
        job_id = f"endpoint-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        bot_id = "endpoint-test-bot"
        
        print("1. Setting up test scenario...")
        
        # Create bot
        await conn.execute("""
            INSERT INTO bots (id, status, current_job_id, assigned_operation)
            VALUES ($1, 'busy', $2, 'sum')
            ON CONFLICT (id) DO UPDATE
            SET status = 'busy', current_job_id = $2
        """, bot_id, job_id)
        
        # Create job in processing state
        await conn.execute("""
            INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at)
            VALUES ($1, 25, 30, 'sum', 'processing', $2, NOW(), NOW())
        """, job_id, bot_id)
        
        print(f"   [OK] Created job {job_id} and bot {bot_id}")
        
        # Step 2: Test the /complete endpoint
        print("\n2. Testing /jobs/{job_id}/complete endpoint...")
        
        async with httpx.AsyncClient() as client:
            complete_response = await client.post(
                f"{API_URL}/jobs/{job_id}/complete",
                json={
                    "bot_id": bot_id,
                    "result": 55,  # 25 + 30 = 55
                    "duration_ms": 5000
                }
            )
            
            print(f"   Status Code: {complete_response.status_code}")
            if complete_response.status_code == 200:
                complete_data = complete_response.json()
                print(f"   [OK] Response: {complete_data}")
            else:
                print(f"   [ERROR] Failed: {complete_response.text}")
                
                # Check if the endpoint exists at all
                try:
                    error_data = complete_response.json()
                    print(f"   Error details: {error_data}")
                except:
                    print(f"   Raw error: {complete_response.text}")
        
        # Step 3: Verify job state after completion
        print("\n3. Verifying job state after completion...")
        
        job_state = await conn.fetchrow("""
            SELECT status, finished_at FROM jobs WHERE id = $1
        """, job_id)
        
        if job_state:
            print(f"   Job Status: {job_state['status']}")
            print(f"   Finished At: {job_state['finished_at']}")
            
            if job_state['status'] == 'succeeded':
                print("   [OK] Job marked as succeeded")
            else:
                print(f"   [ERROR] Job not marked as succeeded: {job_state['status']}")
        
        # Check if result was recorded
        result_record = await conn.fetchrow("""
            SELECT * FROM results WHERE job_id = $1
        """, job_id)
        
        if result_record:
            print(f"   [OK] Result recorded: {dict(result_record)}")
        else:
            print("   [ERROR] No result record found")
        
        # Check bot state
        bot_state = await conn.fetchrow("""
            SELECT status, current_job_id FROM bots WHERE id = $1
        """, bot_id)
        
        if bot_state:
            print(f"   Bot Status: {bot_state['status']}")
            print(f"   Bot Current Job: {bot_state['current_job_id']}")
            
            if bot_state['status'] == 'idle' and bot_state['current_job_id'] is None:
                print("   [OK] Bot properly reset")
            else:
                print("   [ERROR] Bot not properly reset")
        
        # Step 4: Test with a failure scenario
        print("\n4. Testing /jobs/{job_id}/fail endpoint...")
        
        # Create another test job
        fail_job_id = f"fail-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        await conn.execute("""
            INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at)
            VALUES ($1, 15, 20, 'divide', 'processing', $2, NOW(), NOW())
        """, fail_job_id, bot_id)
        
        await conn.execute("""
            UPDATE bots SET current_job_id = $1, status = 'busy' WHERE id = $2
        """, fail_job_id, bot_id)
        
        async with httpx.AsyncClient() as client:
            fail_response = await client.post(
                f"{API_URL}/jobs/{fail_job_id}/fail",
                json={
                    "bot_id": bot_id,
                    "error": "Simulated division error"
                }
            )
            
            print(f"   Status Code: {fail_response.status_code}")
            if fail_response.status_code == 200:
                fail_data = fail_response.json()
                print(f"   [OK] Response: {fail_data}")
            else:
                print(f"   [ERROR] Failed: {fail_response.text}")
        
        # Verify failure state
        fail_job_state = await conn.fetchrow("""
            SELECT status, error, finished_at FROM jobs WHERE id = $1
        """, fail_job_id)
        
        if fail_job_state:
            print(f"   Job Status: {fail_job_state['status']}")
            print(f"   Job Error: {fail_job_state['error']}")
            
            if fail_job_state['status'] == 'failed':
                print("   [OK] Job marked as failed")
        
        # Cleanup
        await conn.execute("DELETE FROM results WHERE job_id IN ($1, $2)", job_id, fail_job_id)
        await conn.execute("DELETE FROM jobs WHERE id IN ($1, $2)", job_id, fail_job_id)
        await conn.execute("DELETE FROM bots WHERE id = $1", bot_id)
        
        await conn.close()
        
        print("\n=== Endpoint Test Complete ===")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing job completion endpoints...")
    success = asyncio.run(test_job_endpoints())
    sys.exit(0 if success else 1)