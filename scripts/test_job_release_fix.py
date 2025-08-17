#!/usr/bin/env python3
"""
Test script to verify the job release bug fix
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
ADMIN_TOKEN = "admin-secret-token"

async def create_stuck_job_scenario():
    """Create a scenario with a stuck job to test release functionality"""
    print("\n=== Testing Job Release Fix ===\n")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Step 1: Create a test job in processing state
        job_id = f"test-job-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        bot_id = "test-bot-1"
        
        print(f"1. Creating test job: {job_id}")
        await conn.execute("""
            INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at)
            VALUES ($1, 10, 20, 'sum', 'processing', $2, NOW(), NOW())
        """, job_id, bot_id)
        
        # Create bot if it doesn't exist
        await conn.execute("""
            INSERT INTO bots (id, status, current_job_id, assigned_operation, health_status)
            VALUES ($1, 'busy', $2, 'sum', 'potentially_stuck')
            ON CONFLICT (id) DO UPDATE
            SET status = 'busy', 
                current_job_id = $2, 
                health_status = 'potentially_stuck',
                stuck_job_id = $2
        """, bot_id, job_id)
        
        print(f"   [OK] Job created in 'processing' state")
        print(f"   [OK] Bot {bot_id} marked as busy with job")
        
        # Step 2: Test the release endpoint
        print(f"\n2. Testing job release endpoint...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_URL}/jobs/{job_id}/release",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
            )
            
            if response.status_code == 200:
                print(f"   [OK] Release endpoint returned success: {response.json()}")
            else:
                print(f"   [ERROR] Release endpoint failed: {response.status_code} - {response.text}")
                return False
        
        # Step 3: Verify job state
        print(f"\n3. Verifying job state after release...")
        
        job_result = await conn.fetchrow("""
            SELECT status, claimed_by, error FROM jobs WHERE id = $1
        """, job_id)
        
        if job_result:
            if job_result['status'] == 'pending' and job_result['claimed_by'] is None:
                print(f"   [OK] Job status: {job_result['status']}")
                print(f"   [OK] Job claimed_by: {job_result['claimed_by']}")
                print(f"   [OK] Job error note: {job_result['error']}")
            else:
                print(f"   [ERROR] Job not properly released!")
                print(f"   Status: {job_result['status']} (expected: pending)")
                print(f"   Claimed by: {job_result['claimed_by']} (expected: None)")
                return False
        
        # Step 4: Verify bot state
        print(f"\n4. Verifying bot state after release...")
        
        bot_result = await conn.fetchrow("""
            SELECT status, current_job_id, health_status, stuck_job_id FROM bots WHERE id = $1
        """, bot_id)
        
        if bot_result:
            if (bot_result['status'] == 'idle' and 
                bot_result['current_job_id'] is None and
                bot_result['health_status'] == 'normal' and
                bot_result['stuck_job_id'] is None):
                print(f"   [OK] Bot status: {bot_result['status']}")
                print(f"   [OK] Bot current_job_id: {bot_result['current_job_id']}")
                print(f"   [OK] Bot health_status: {bot_result['health_status']}")
                print(f"   [OK] Bot stuck_job_id: {bot_result['stuck_job_id']}")
            else:
                print(f"   [ERROR] Bot not properly reset!")
                print(f"   Status: {bot_result['status']} (expected: idle)")
                print(f"   Current job: {bot_result['current_job_id']} (expected: None)")
                print(f"   Health status: {bot_result['health_status']} (expected: normal)")
                print(f"   Stuck job: {bot_result['stuck_job_id']} (expected: None)")
                return False
        
        # Cleanup
        await conn.execute("DELETE FROM jobs WHERE id = $1", job_id)
        await conn.execute("DELETE FROM bots WHERE id = $1", bot_id)
        
        await conn.close()
        
        print("\n=== TEST PASSED! ===")
        print("\nThe job release bug has been fixed successfully!")
        print("- Jobs are properly reset to 'pending' state")
        print("- Bots are properly reset to 'idle' state")
        print("- Health monitoring fields are working correctly")
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_error_cases():
    """Test error handling in release endpoint"""
    print("\n\n=== Testing Error Cases ===\n")
    
    async with httpx.AsyncClient() as client:
        # Test 1: Non-existent job
        print("1. Testing release of non-existent job...")
        response = await client.post(
            f"{API_URL}/jobs/non-existent-job/release",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
        )
        
        if response.status_code == 404:
            print("   [OK] Correctly returned 404 for non-existent job")
        else:
            print(f"   [ERROR] Unexpected response: {response.status_code}")
        
        # Test 2: Already completed job
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Create a succeeded job
        succeeded_job_id = "test-succeeded-job"
        await conn.execute("""
            INSERT INTO jobs (id, a, b, operation, status, finished_at)
            VALUES ($1, 5, 5, 'sum', 'succeeded', NOW())
        """, succeeded_job_id)
        
        print("\n2. Testing release of already succeeded job...")
        response = await client.post(
            f"{API_URL}/jobs/{succeeded_job_id}/release",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
        )
        
        if response.status_code == 400:
            print("   [OK] Correctly returned 400 for succeeded job")
        else:
            print(f"   [ERROR] Unexpected response: {response.status_code}")
        
        # Cleanup
        await conn.execute("DELETE FROM jobs WHERE id = $1", succeeded_job_id)
        await conn.close()

if __name__ == "__main__":
    print("Starting job release fix test...")
    print(f"API URL: {API_URL}")
    print(f"Database: {DATABASE_URL}")
    
    # Run tests
    success = asyncio.run(create_stuck_job_scenario())
    
    if success:
        asyncio.run(test_error_cases())
        sys.exit(0)
    else:
        sys.exit(1)