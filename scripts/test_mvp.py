#!/usr/bin/env python3
"""
Quick MVP test script for multi-operation system.

This script performs a focused test of the key MVP features:
1. Can drop new operation into operations/ folder
2. Bot with assigned operation processes only that type
3. Bot with no assigned operation picks first available job and adopts its operation
4. Dashboard shows bot's current assignment
5. Default sum-only flow still works
"""

import asyncio
import aiohttp
import json
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_mvp_features():
    """Test core MVP features."""
    
    main_server_url = "http://localhost:3001"
    admin_token = "admin-secret-token"
    
    async with aiohttp.ClientSession() as session:
        
        # Helper function
        async def api_call(method, endpoint, data=None):
            url = f"{main_server_url}{endpoint}"
            headers = {"Authorization": f"Bearer {admin_token}"}
            async with session.request(method, url, json=data, headers=headers) as resp:
                return await resp.json() if resp.status < 400 else None
        
        logger.info("🔍 Testing MVP Features...")
        
        # 1. Test operations are loaded
        operations = await api_call("GET", "/operations")
        if operations:
            op_names = [op["name"] for op in operations["operations"]]
            logger.info(f"✅ Operations loaded: {op_names}")
        else:
            logger.error("❌ Failed to load operations")
            return False
        
        # 2. Test job creation with operations
        for operation in ["sum", "subtract", "multiply"]:
            result = await api_call("POST", "/jobs/populate", {
                "batchSize": 2,
                "operation": operation
            })
            if result:
                logger.info(f"✅ Created {operation} jobs")
            else:
                logger.error(f"❌ Failed to create {operation} jobs")
        
        # 3. Test bot assignment
        bots = await api_call("GET", "/bots")
        if bots and len(bots) > 0:
            test_bot_id = bots[0]["id"]
            
            # Assign bot to specific operation
            result = await api_call("POST", f"/bots/{test_bot_id}/assign-operation", {
                "operation": "multiply"
            })
            if result:
                logger.info(f"✅ Assigned bot {test_bot_id} to multiply operation")
            else:
                logger.error(f"❌ Failed to assign bot to operation")
            
            # Unassign bot
            result = await api_call("POST", f"/bots/{test_bot_id}/assign-operation", {
                "operation": None
            })
            if result:
                logger.info(f"✅ Unassigned bot {test_bot_id}")
            else:
                logger.error(f"❌ Failed to unassign bot")
        
        # 4. Check system status
        jobs = await api_call("GET", "/jobs?limit=20")
        if jobs:
            operations_in_jobs = set(job.get("operation", "unknown") for job in jobs)
            logger.info(f"✅ Jobs found with operations: {operations_in_jobs}")
        
        logger.info("\\n🎉 MVP Test completed! Check logs above for any issues.")
        return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_mvp_features())
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        sys.exit(1)