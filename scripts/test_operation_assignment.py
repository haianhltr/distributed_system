#!/usr/bin/env python3
"""
Test script to verify bot operation assignment is working correctly
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

async def test_operation_assignment():
    """Test that bots only pick up jobs for their assigned operations"""
    print("\n=== Testing Bot Operation Assignment ===\n")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Step 1: Check current bot assignments
        print("1. Current bot assignments:")
        
        async with httpx.AsyncClient() as client:
            bots_response = await client.get(f"{API_URL}/bots")
            if bots_response.status_code == 200:
                bots = bots_response.json()
                for bot in bots:
                    if bot['status'] != 'down':
                        print(f"   {bot['id']}: assigned_operation = '{bot['assigned_operation']}'")
            else:
                print(f"   [ERROR] Failed to get bots: {bots_response.status_code}")
                return False
        
        # Step 2: Create jobs for each operation type
        print("\n2. Creating test jobs...")
        
        operations_to_test = ['sum', 'multiply', 'divide', 'subtract']
        created_jobs = {}
        
        async with httpx.AsyncClient() as client:
            for operation in operations_to_test:
                response = await client.post(
                    f"{API_URL}/jobs/populate",
                    json={"batchSize": 1, "operation": operation},
                    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    job_id = data['jobs'][0]['id']
                    created_jobs[operation] = job_id
                    print(f"   Created {operation} job: {job_id[:8]}...")
                else:
                    print(f"   [ERROR] Failed to create {operation} job: {response.status_code}")
        
        # Step 3: Wait for bots to process jobs (or not)
        print("\n3. Waiting for bot activity (15 seconds)...")
        
        for i in range(3):
            await asyncio.sleep(5)
            print(f"   Checking... ({(i+1)*5}s)")
        
        # Step 4: Check which jobs were claimed
        print("\n4. Checking job assignments...")
        
        expected_assignments = {
            'sum': ['bot-docker-1', 'bot-docker-2'],  # Both assigned to sum
            'multiply': ['bot-docker-3'],              # Only bot-3 assigned to multiply
            'divide': [],                              # No bots assigned to divide
            'subtract': []                             # No bots assigned to subtract
        }
        
        assignment_results = {}
        all_correct = True
        
        for operation, job_id in created_jobs.items():
            job_info = await conn.fetchrow("""
                SELECT status, claimed_by FROM jobs WHERE id = $1
            """, job_id)
            
            if job_info:
                status = job_info['status']
                claimed_by = job_info['claimed_by']
                assignment_results[operation] = (status, claimed_by)
                
                expected_bots = expected_assignments[operation]
                
                if status in ['pending']:
                    if len(expected_bots) == 0:
                        print(f"   ✓ {operation} job: PENDING (correct - no bots assigned)")
                    else:
                        print(f"   ✗ {operation} job: PENDING (wrong - should be claimed by {expected_bots})")
                        all_correct = False
                        
                elif status in ['claimed', 'processing', 'succeeded', 'failed']:
                    if claimed_by in expected_bots:
                        print(f"   ✓ {operation} job: {status.upper()} by {claimed_by} (correct)")
                    else:
                        print(f"   ✗ {operation} job: {status.upper()} by {claimed_by} (wrong - should be {expected_bots})")
                        all_correct = False
                else:
                    print(f"   ? {operation} job: {status} by {claimed_by} (unknown status)")
        
        # Step 5: Summary
        print(f"\n5. Test Results:")
        
        if all_correct:
            print("   [SUCCESS] All bots respected their operation assignments!")
            print("   - sum jobs claimed by sum-assigned bots")
            print("   - multiply jobs claimed by multiply-assigned bots")  
            print("   - divide/subtract jobs remained unclaimed (no assigned bots)")
        else:
            print("   [FAILURE] Some bots violated their operation assignments!")
            print("   This indicates the job claiming logic is not working correctly.")
        
        # Cleanup
        for job_id in created_jobs.values():
            await conn.execute("DELETE FROM results WHERE job_id = $1", job_id)
            await conn.execute("DELETE FROM jobs WHERE id = $1", job_id)
        
        await conn.close()
        return all_correct
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing bot operation assignment functionality...")
    success = asyncio.run(test_operation_assignment())
    sys.exit(0 if success else 1)