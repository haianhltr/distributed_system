"""
Intensive Race Condition Test

Tests the fixed job claiming system with high concurrency to ensure
FOR UPDATE SKIP LOCKED completely eliminates race conditions.
"""

import asyncio
import aiohttp
import time


async def intensive_race_test():
    """Test with high concurrency to stress test the fix"""
    
    MAIN_SERVER_URL = "http://localhost:3001"
    ADMIN_TOKEN = "admin-secret-token"
    NUM_BOTS = 20  # High concurrency
    NUM_JOBS = 10  # Fewer jobs than bots to create contention
    
    print(f"INTENSIVE RACE CONDITION TEST")
    print(f"   Bots: {NUM_BOTS}")
    print(f"   Jobs: {NUM_JOBS}")
    print(f"   Expected: {NUM_JOBS} successful claims, {NUM_BOTS - NUM_JOBS} failures")
    print(f"   Testing: No duplicate assignments or race conditions")
    print()
    
    # Create jobs
    print("1. Creating test jobs...")
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        async with session.post(
            f"{MAIN_SERVER_URL}/jobs/populate",
            json={"batchSize": NUM_JOBS},
            headers=headers
        ) as response:
            if response.status == 200:
                result = await response.json()
                print(f"   OK Created {result['created']} jobs")
            else:
                print(f"   FAIL Failed to create jobs: {response.status}")
                return
    
    # Create bot sessions
    print("2. Creating bot sessions...")
    bot_sessions = []
    for i in range(NUM_BOTS):
        session = aiohttp.ClientSession()
        bot_sessions.append((f"stress-bot-{i:03d}", session))
    
    try:
        # Register all bots
        print("3. Registering bots...")
        register_tasks = []
        for bot_id, session in bot_sessions:
            task = asyncio.create_task(register_bot(bot_id, session, MAIN_SERVER_URL))
            register_tasks.append(task)
        
        register_results = await asyncio.gather(*register_tasks, return_exceptions=True)
        successful_registrations = sum(1 for r in register_results if r is True)
        print(f"   OK {successful_registrations}/{NUM_BOTS} bots registered")
        
        # Test multiple rounds of simultaneous claims
        for round_num in range(3):
            print(f"\n4.{round_num + 1} ROUND {round_num + 1}: Simultaneous job claiming...")
            
            start_time = time.time()
            
            # All bots try to claim simultaneously
            claim_tasks = []
            for bot_id, session in bot_sessions:
                task = asyncio.create_task(claim_job_once(bot_id, session, MAIN_SERVER_URL))
                claim_tasks.append(task)
            
            results = await asyncio.gather(*claim_tasks, return_exceptions=True)
            end_time = time.time()
            
            # Analyze results
            successful_claims = [r for r in results if isinstance(r, dict) and r.get('success')]
            failed_claims = [r for r in results if not (isinstance(r, dict) and r.get('success'))]
            
            print(f"   Results in {end_time - start_time:.3f}s:")
            print(f"   OK Successful: {len(successful_claims)}")
            print(f"   FAIL Failed: {len(failed_claims)}")
            
            # Verify no duplicate job assignments
            if successful_claims:
                job_ids = [claim['job_id'] for claim in successful_claims]
                unique_jobs = set(job_ids)
                
                if len(job_ids) == len(unique_jobs):
                    print(f"   PASS No duplicate assignments detected")
                else:
                    duplicates = len(job_ids) - len(unique_jobs)
                    print(f"   RACE CONDITION: {duplicates} duplicate assignments!")
                    
                    # Show duplicates
                    from collections import Counter
                    job_counts = Counter(job_ids)
                    for job_id, count in job_counts.items():
                        if count > 1:
                            print(f"      Job {job_id} claimed by {count} bots")
            
            # Complete the jobs
            print(f"   Completing claimed jobs...")
            complete_tasks = []
            for claim in successful_claims:
                task = asyncio.create_task(
                    complete_job(claim['bot_id'], claim['job_id'], bot_sessions, MAIN_SERVER_URL)
                )
                complete_tasks.append(task)
            
            if complete_tasks:
                await asyncio.gather(*complete_tasks, return_exceptions=True)
                print(f"   OK Completed {len(complete_tasks)} jobs")
        
        # Final consistency check
        print(f"\n5. Final consistency verification...")
        await verify_final_consistency()
        
    finally:
        # Cleanup
        print(f"\n6. Cleaning up...")
        cleanup_tasks = []
        for bot_id, session in bot_sessions:
            task = asyncio.create_task(cleanup_bot(bot_id, session, MAIN_SERVER_URL, ADMIN_TOKEN))
            cleanup_tasks.append(task)
        
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        print(f"   OK Cleaned up {NUM_BOTS} bots")


async def register_bot(bot_id: str, session: aiohttp.ClientSession, server_url: str):
    """Register a single bot"""
    try:
        async with session.post(
            f"{server_url}/bots/register",
            json={"bot_id": bot_id}
        ) as response:
            return response.status == 200
    except:
        return False


async def claim_job_once(bot_id: str, session: aiohttp.ClientSession, server_url: str):
    """Attempt to claim one job"""
    try:
        async with session.post(
            f"{server_url}/jobs/claim",
            json={"bot_id": bot_id}
        ) as response:
            if response.status == 200:
                job = await response.json()
                return {
                    "success": True,
                    "bot_id": bot_id,
                    "job_id": job['id']
                }
            else:
                return {"success": False, "bot_id": bot_id, "status": response.status}
    except Exception as e:
        return {"success": False, "bot_id": bot_id, "error": str(e)}


async def complete_job(bot_id: str, job_id: str, bot_sessions: list, server_url: str):
    """Complete a claimed job"""
    # Find the session for this bot
    session = None
    for bid, sess in bot_sessions:
        if bid == bot_id:
            session = sess
            break
    
    if not session:
        return
    
    try:
        # Start job
        async with session.post(
            f"{server_url}/jobs/{job_id}/start",
            json={"bot_id": bot_id}
        ) as response:
            pass
        
        # Complete job
        async with session.post(
            f"{server_url}/jobs/{job_id}/complete",
            json={
                "bot_id": bot_id,
                "result": 42,
                "duration_ms": 100
            }
        ) as response:
            pass
    except:
        pass


async def cleanup_bot(bot_id: str, session: aiohttp.ClientSession, server_url: str, admin_token: str):
    """Cleanup a test bot"""
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        async with session.delete(
            f"{server_url}/bots/{bot_id}",
            headers=headers
        ) as response:
            pass
    except:
        pass
    finally:
        await session.close()


async def verify_final_consistency():
    """Verify database consistency"""
    import asyncpg
    
    try:
        conn = await asyncpg.connect("postgresql://ds_user:ds_password@localhost:5432/distributed_system")
        
        # Check for any inconsistencies
        duplicates = await conn.fetchval("""
            SELECT COUNT(*) - COUNT(DISTINCT current_job_id)
            FROM bots 
            WHERE current_job_id IS NOT NULL AND deleted_at IS NULL
        """)
        
        orphaned_bots = await conn.fetchval("""
            SELECT COUNT(*)
            FROM bots b
            LEFT JOIN jobs j ON b.current_job_id = j.id
            WHERE b.current_job_id IS NOT NULL 
            AND j.id IS NULL
            AND b.deleted_at IS NULL
        """)
        
        if duplicates == 0 and orphaned_bots == 0:
            print("   PASS Database is fully consistent")
        else:
            print(f"   FAIL Issues found: {duplicates} duplicates, {orphaned_bots} orphaned")
            
        await conn.close()
        
    except Exception as e:
        print(f"   ERROR Failed to verify consistency: {e}")


if __name__ == "__main__":
    asyncio.run(intensive_race_test())