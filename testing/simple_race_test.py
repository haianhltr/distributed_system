"""
Simple Race Condition Test

Demonstrates the exact race condition issue we found in the job claiming system.
"""

import asyncio
import aiohttp
import json
import time
from typing import List, Dict, Any


async def test_race_condition():
    """Simple test to demonstrate race condition in job claiming"""
    
    # Configuration
    MAIN_SERVER_URL = "http://localhost:3001"
    ADMIN_TOKEN = "admin-secret-token"
    NUM_BOTS = 10
    
    print(f"Testing race condition with {NUM_BOTS} bots claiming jobs simultaneously...")
    
    # Step 1: Create some jobs
    print("1. Creating test jobs...")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        async with session.post(
            f"{MAIN_SERVER_URL}/jobs/populate",
            json={"batchSize": 5},
            headers=headers
        ) as response:
            if response.status == 200:
                result = await response.json()
                print(f"   Created {result['created']} jobs")
            else:
                print(f"   Failed to create jobs: {response.status}")
                return
    
    # Step 2: Create concurrent bots
    print("2. Setting up concurrent bots...")
    bot_sessions = []
    for i in range(NUM_BOTS):
        session = aiohttp.ClientSession()
        bot_sessions.append((f"test-bot-{i:02d}", session))
    
    try:
        # Step 3: Register all bots
        print("3. Registering bots...")
        for bot_id, session in bot_sessions:
            async with session.post(
                f"{MAIN_SERVER_URL}/bots/register",
                json={"bot_id": bot_id}
            ) as response:
                if response.status == 200:
                    print(f"   OK {bot_id} registered")
                else:
                    print(f"   FAIL {bot_id} failed to register: {response.status}")
        
        # Step 4: All bots try to claim jobs simultaneously
        print("4. Starting simultaneous job claiming...")
        start_time = time.time()
        
        async def claim_job(bot_id: str, session: aiohttp.ClientSession):
            try:
                async with session.post(
                    f"{MAIN_SERVER_URL}/jobs/claim",
                    json={"bot_id": bot_id}
                ) as response:
                    if response.status == 200:
                        job = await response.json()
                        print(f"   OK {bot_id} claimed job {job['id']}")
                        return {"bot_id": bot_id, "job_id": job['id'], "success": True}
                    else:
                        error_text = await response.text()
                        print(f"   FAIL {bot_id} failed: {response.status} - {error_text}")
                        return {"bot_id": bot_id, "error": error_text, "success": False}
            except Exception as e:
                print(f"   ERROR {bot_id} exception: {e}")
                return {"bot_id": bot_id, "error": str(e), "success": False}
        
        # Execute all claims simultaneously
        tasks = [claim_job(bot_id, session) for bot_id, session in bot_sessions]
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        
        # Step 5: Analyze results
        print(f"\n5. Results (completed in {end_time - start_time:.3f} seconds):")
        
        successful_claims = [r for r in results if r['success']]
        failed_claims = [r for r in results if not r['success']]
        
        print(f"   Successful claims: {len(successful_claims)}")
        print(f"   Failed claims: {len(failed_claims)}")
        
        if successful_claims:
            print("   Successful bots:")
            for claim in successful_claims:
                print(f"     - {claim['bot_id']} -> job {claim['job_id']}")
        
        if failed_claims:
            print("   Failed bots:")
            for claim in failed_claims[:5]:  # Show first 5 failures
                print(f"     - {claim['bot_id']}: {claim.get('error', 'Unknown error')}")
        
        # Step 6: Check for race conditions by verifying database state
        print("\n6. Checking for race conditions...")
        await check_database_consistency()
        
    finally:
        # Cleanup
        print("\n7. Cleaning up...")
        for bot_id, session in bot_sessions:
            try:
                headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
                async with session.delete(
                    f"{MAIN_SERVER_URL}/bots/{bot_id}",
                    headers=headers
                ) as response:
                    pass
            except:
                pass
            finally:
                await session.close()


async def check_database_consistency():
    """Check database for consistency issues"""
    import asyncpg
    
    DATABASE_URL = "postgresql://ds_user:ds_password@localhost:5432/distributed_system"
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Check for duplicate job assignments
        duplicates = await conn.fetch("""
            SELECT current_job_id, array_agg(id) as bot_ids, COUNT(*) as count
            FROM bots 
            WHERE current_job_id IS NOT NULL
            AND deleted_at IS NULL
            GROUP BY current_job_id
            HAVING COUNT(*) > 1
        """)
        
        if duplicates:
            print("   RACE CONDITION DETECTED!")
            for dup in duplicates:
                print(f"     Job {dup['current_job_id']} assigned to {dup['count']} bots: {dup['bot_ids']}")
        
        # Check for orphaned job assignments
        orphaned = await conn.fetch("""
            SELECT b.id, b.current_job_id
            FROM bots b
            LEFT JOIN jobs j ON b.current_job_id = j.id
            WHERE b.current_job_id IS NOT NULL 
            AND j.id IS NULL
            AND b.deleted_at IS NULL
        """)
        
        if orphaned:
            print("   ORPHANED ASSIGNMENTS DETECTED!")
            for orphan in orphaned:
                print(f"     Bot {orphan['id']} has non-existent job {orphan['current_job_id']}")
        
        # Check for mismatched job claims
        mismatched = await conn.fetch("""
            SELECT j.id, j.claimed_by, b.id as bot_id, b.current_job_id
            FROM jobs j
            JOIN bots b ON j.claimed_by = b.id
            WHERE j.status IN ('claimed', 'processing')
            AND (b.current_job_id != j.id OR b.deleted_at IS NOT NULL)
        """)
        
        if mismatched:
            print("   MISMATCHED CLAIMS DETECTED!")
            for mismatch in mismatched:
                print(f"     Job {mismatch['id']} claimed by {mismatch['claimed_by']} but bot has job {mismatch['current_job_id']}")
        
        if not duplicates and not orphaned and not mismatched:
            print("   OK No race conditions detected - database is consistent")
            
        await conn.close()
        
    except Exception as e:
        print(f"   ERROR Failed to check database consistency: {e}")


if __name__ == "__main__":
    asyncio.run(test_race_condition())