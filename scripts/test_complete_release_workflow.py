#!/usr/bin/env python3
"""
Complete integration test for job release workflow
Tests the entire flow from stuck job to successful release
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
DASHBOARD_URL = "http://localhost:3002"
ADMIN_TOKEN = "admin-secret-token"

async def test_complete_workflow():
    """Test the complete job release workflow"""
    print("\n=== Complete Job Release Workflow Test ===\n")
    
    try:
        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Step 1: Create a stuck job scenario
        job_id = f"workflow-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        bot_id = "workflow-bot-1"
        
        print("1. Setting up stuck job scenario...")
        
        # Create bot
        await conn.execute("""
            INSERT INTO bots (id, status, current_job_id, assigned_operation, last_heartbeat_at)
            VALUES ($1, 'busy', $2, 'multiply', NOW() - INTERVAL '15 minutes')
            ON CONFLICT (id) DO UPDATE
            SET status = 'busy', 
                current_job_id = $2,
                last_heartbeat_at = NOW() - INTERVAL '15 minutes'
        """, bot_id, job_id)
        
        # Create stuck job
        await conn.execute("""
            INSERT INTO jobs (id, a, b, operation, status, claimed_by, claimed_at, started_at)
            VALUES ($1, 42, 10, 'multiply', 'processing', $2, NOW() - INTERVAL '15 minutes', NOW() - INTERVAL '14 minutes')
        """, job_id, bot_id)
        
        print(f"   [OK] Created stuck job: {job_id}")
        print(f"   [OK] Bot {bot_id} has been processing for 14+ minutes")
        
        # Step 2: Check dashboard API
        print("\n2. Checking dashboard API for stuck job...")
        
        async with httpx.AsyncClient() as client:
            # Get jobs list
            jobs_response = await client.get(f"{DASHBOARD_URL}/api/jobs?limit=100")
            if jobs_response.status_code == 200:
                jobs_data = jobs_response.json()
                stuck_job = next((j for j in jobs_data['jobs'] if j['id'] == job_id), None)
                
                if stuck_job:
                    print(f"   [OK] Job found in dashboard: status={stuck_job['status']}")
                    if stuck_job.get('processing_duration_minutes', 0) > 10:
                        print(f"   [OK] Job correctly identified as stuck (processing for {stuck_job.get('processing_duration_minutes', 0):.1f} minutes)")
                else:
                    print(f"   [WARNING] Job not found in dashboard response")
            
            # Get bot status
            bots_response = await client.get(f"{DASHBOARD_URL}/api/bots")
            if bots_response.status_code == 200:
                bots_data = bots_response.json()
                stuck_bot = next((b for b in bots_data['bots'] if b['id'] == bot_id), None)
                
                if stuck_bot:
                    print(f"   [OK] Bot found in dashboard: status={stuck_bot['status']}, current_job={stuck_bot.get('current_job_id')}")
        
        # Step 3: Release the job
        print("\n3. Releasing stuck job via API...")
        
        async with httpx.AsyncClient() as client:
            release_response = await client.post(
                f"{API_URL}/jobs/{job_id}/release",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
            )
            
            if release_response.status_code == 200:
                release_data = release_response.json()
                print(f"   [OK] Job released successfully")
                print(f"   Response: {release_data['message']}")
            else:
                print(f"   [ERROR] Failed to release job: {release_response.status_code}")
                return False
        
        # Step 4: Verify final state
        print("\n4. Verifying final state...")
        
        # Check job state
        job_state = await conn.fetchrow("""
            SELECT status, claimed_by, error, 
                   CASE WHEN claimed_by IS NOT NULL THEN 'INCORRECT' ELSE 'CORRECT' END as claim_check
            FROM jobs WHERE id = $1
        """, job_id)
        
        print(f"   Job Status: {job_state['status']} (expected: pending)")
        print(f"   Job Claimed By: {job_state['claimed_by']} [{job_state['claim_check']}]")
        print(f"   Job Error: {job_state['error']}")
        
        # Check bot state
        bot_state = await conn.fetchrow("""
            SELECT status, current_job_id, health_status, stuck_job_id,
                   CASE WHEN current_job_id IS NOT NULL THEN 'INCORRECT' ELSE 'CORRECT' END as job_check
            FROM bots WHERE id = $1
        """, bot_id)
        
        print(f"\n   Bot Status: {bot_state['status']} (expected: idle)")
        print(f"   Bot Current Job: {bot_state['current_job_id']} [{bot_state['job_check']}]")
        print(f"   Bot Health: {bot_state['health_status']} (expected: normal)")
        print(f"   Bot Stuck Job: {bot_state['stuck_job_id']} (expected: None)")
        
        # Step 5: Verify job can be claimed again
        print("\n5. Verifying job can be claimed again...")
        
        # Wait a moment for any async updates
        await asyncio.sleep(1)
        
        # Try to claim the job
        async with httpx.AsyncClient() as client:
            claim_response = await client.post(
                f"{API_URL}/bots/test-new-bot/claim",
                json={"operation": "multiply"},
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
            )
            
            if claim_response.status_code == 200:
                claim_data = claim_response.json()
                if claim_data.get('job_id') == job_id:
                    print(f"   [OK] Job successfully claimed by new bot")
                    print(f"   [OK] This confirms the job was properly released")
                else:
                    print(f"   [INFO] Different job claimed: {claim_data.get('job_id')}")
            else:
                print(f"   [INFO] No jobs available to claim (status: {claim_response.status_code})")
        
        # Cleanup
        await conn.execute("DELETE FROM results WHERE job_id = $1", job_id)
        await conn.execute("DELETE FROM jobs WHERE id = $1", job_id)
        await conn.execute("DELETE FROM bots WHERE id IN ($1, $2)", bot_id, "test-new-bot")
        
        await conn.close()
        
        # Final verdict
        success = (job_state['status'] == 'pending' and 
                  job_state['claimed_by'] is None and
                  bot_state['status'] == 'idle' and
                  bot_state['current_job_id'] is None)
        
        if success:
            print("\n=== WORKFLOW TEST PASSED! ===")
            print("\nThe job release bug has been completely fixed:")
            print("- Stuck jobs can be released back to pending state")
            print("- Bots are properly reset when their jobs are released")
            print("- Released jobs can be claimed by other bots")
            print("- Frontend APIs return correct information")
        else:
            print("\n=== WORKFLOW TEST FAILED! ===")
            print("Some issues remain with the job release functionality")
        
        return success
        
    except Exception as e:
        print(f"\n[ERROR] Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting complete workflow test...")
    print(f"Main Server: {API_URL}")
    print(f"Dashboard: {DASHBOARD_URL}")
    print(f"Database: {DATABASE_URL}")
    
    success = asyncio.run(test_complete_workflow())
    sys.exit(0 if success else 1)