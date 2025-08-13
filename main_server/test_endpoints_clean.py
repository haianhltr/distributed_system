#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive API endpoint tests for the Distributed Job Processing System
"""

import asyncio
import json
import random
import time
from typing import Dict, Any, Optional
import aiohttp
import sys

class APITester:
    def __init__(self, base_url: str = "http://localhost:3001"):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     headers: Optional[Dict] = None) -> Dict[str, Any]:
        """Make HTTP request and return result with status"""
        if not self.session:
            raise RuntimeError("Session not initialized")
            
        url = f"{self.base_url}{endpoint}"
        
        # Default headers
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        
        try:
            async with self.session.request(
                method, 
                url, 
                json=data,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                try:
                    response_data = await response.json()
                except:
                    response_data = {"error": "Invalid JSON response"}
                
                return {
                    "status": response.status,
                    "data": response_data,
                    "success": 200 <= response.status < 300
                }
        except Exception as e:
            return {
                "status": 0,
                "data": {"error": str(e)},
                "success": False
            }

class ComprehensiveAPITester:
    def __init__(self, base_url: str = "http://localhost:3001"):
        self.base_url = base_url
        self.test_bot_id = f"test-bot-{int(time.time() * 1000)}"
        self.test_results = []
        
    async def test_health_check(self) -> Dict[str, Any]:
        """Test health check endpoint"""
        print(">>> Testing health check...")
        
        async with APITester(self.base_url) as tester:
            result = await tester.request("GET", "/healthz")
            success = result["status"] == 200 and "status" in result["data"]
            
            return {
                "test": "health_check",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_metrics(self) -> Dict[str, Any]:
        """Test metrics endpoint"""
        print(">>> Testing metrics...")
        
        async with APITester(self.base_url) as tester:
            result = await tester.request("GET", "/metrics")
            success = result["status"] == 200 and "timestamp" in result["data"]
            
            return {
                "test": "metrics",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_bot_registration(self) -> Dict[str, Any]:
        """Test bot registration endpoint"""
        print(">>> Testing bot registration...")
        
        async with APITester(self.base_url) as tester:
            data = {"bot_id": self.test_bot_id}
            result = await tester.request("POST", "/bots/register", data)
            success = result["status"] == 200 and result["data"].get("status") == "registered"
            
            return {
                "test": "bot_registration",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_bot_heartbeat(self) -> Dict[str, Any]:
        """Test bot heartbeat endpoint"""
        print(">>> Testing bot heartbeat...")
        
        async with APITester(self.base_url) as tester:
            data = {"bot_id": self.test_bot_id}
            result = await tester.request("POST", "/bots/heartbeat", data)
            success = result["status"] == 200 and result["data"].get("status") == "ok"
            
            return {
                "test": "bot_heartbeat",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_get_bots(self) -> Dict[str, Any]:
        """Test get bots endpoint"""
        print(">>> Testing get bots...")
        
        async with APITester(self.base_url) as tester:
            result = await tester.request("GET", "/bots")
            success = result["status"] == 200 and isinstance(result["data"], list)
            
            return {
                "test": "get_bots",
                "success": success,
                "status": result["status"],
                "details": f"Found {len(result['data'])} bots" if success else f"Failed: {result}"
            }
        
    async def test_job_populate(self) -> Dict[str, Any]:
        """Test job population endpoint"""
        print(">>> Testing job population...")
        
        async with APITester(self.base_url) as tester:
            headers = {"Authorization": "Bearer admin-secret-token"}
            data = {"batchSize": 3}
            result = await tester.request("POST", "/jobs/populate", data, headers)
            success = result["status"] == 200 and result["data"].get("created") == 3
            
            return {
                "test": "job_populate",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_get_jobs(self) -> Dict[str, Any]:
        """Test get jobs endpoint"""
        print(">>> Testing get jobs...")
        
        async with APITester(self.base_url) as tester:
            result = await tester.request("GET", "/jobs?limit=5")
            success = result["status"] == 200 and isinstance(result["data"], list)
            
            return {
                "test": "get_jobs",
                "success": success,
                "status": result["status"],
                "details": f"Found {len(result['data'])} jobs" if success else f"Failed: {result}"
            }
        
    async def test_job_claim(self) -> Dict[str, Any]:
        """Test job claiming endpoint"""
        print(">>> Testing job claim...")
        
        async with APITester(self.base_url) as tester:
            data = {"bot_id": self.test_bot_id}
            result = await tester.request("POST", "/jobs/claim", data)
            # Should succeed (200) if job available, or 204 if no jobs
            success = result["status"] in [200, 204]
            
            return {
                "test": "job_claim",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_job_workflow(self) -> Dict[str, Any]:
        """Test complete job workflow: claim -> start -> complete"""
        print(">>> Testing job workflow...")
        
        async with APITester(self.base_url) as tester:
            # First, claim a job
            claim_data = {"bot_id": self.test_bot_id}
            claim_result = await tester.request("POST", "/jobs/claim", claim_data)
            
            if claim_result["status"] == 204:
                return {
                    "test": "job_workflow",
                    "success": True,
                    "status": 204,
                    "details": "No jobs available to test workflow"
                }
            
            if claim_result["status"] != 200:
                return {
                    "test": "job_workflow",
                    "success": False,
                    "status": claim_result["status"],
                    "details": f"Failed to claim job: {claim_result}"
                }
            
            job = claim_result["data"]
            job_id = job["id"]
            
            # Start the job
            start_data = {"bot_id": self.test_bot_id}
            start_result = await tester.request("POST", f"/jobs/{job_id}/start", start_data)
            
            if start_result["status"] != 200:
                return {
                    "test": "job_workflow",
                    "success": False,
                    "status": start_result["status"],
                    "details": f"Failed to start job: {start_result}"
                }
            
            # Complete the job
            complete_data = {
                "bot_id": self.test_bot_id,
                "sum": job["a"] + job["b"],
                "duration_ms": 1000
            }
            complete_result = await tester.request("POST", f"/jobs/{job_id}/complete", complete_data)
            
            success = complete_result["status"] == 200
            return {
                "test": "job_workflow",
                "success": success,
                "status": complete_result["status"],
                "details": complete_result["data"] if success else f"Failed to complete: {complete_result}"
            }
        
    async def test_bot_deletion(self) -> Dict[str, Any]:
        """Test bot deletion endpoint"""
        print(">>> Testing bot deletion...")
        
        async with APITester(self.base_url) as tester:
            headers = {"Authorization": "Bearer admin-secret-token"}
            result = await tester.request("DELETE", f"/bots/{self.test_bot_id}", headers=headers)
            success = result["status"] == 200 and result["data"].get("status") == "deleted"
            
            return {
                "test": "bot_deletion",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }
        
    async def test_metrics_summary(self) -> Dict[str, Any]:
        """Test metrics summary endpoint"""
        print(">>> Testing metrics summary...")
        
        async with APITester(self.base_url) as tester:
            result = await tester.request("GET", "/metrics/summary")
            success = result["status"] == 200 and "jobs" in result["data"] and "bots" in result["data"]
            
            return {
                "test": "metrics_summary",
                "success": success,
                "status": result["status"],
                "details": result["data"] if success else f"Failed: {result}"
            }

async def run_comprehensive_tests():
    """Run all comprehensive API tests"""
    print(">>> Starting comprehensive endpoint tests...")
    print("Target:", "http://localhost:3001")
    print("Waiting 3 seconds for system to be ready...")
    await asyncio.sleep(3)
    
    tester = ComprehensiveAPITester()
    
    # List of all tests to run
    tests = [
        tester.test_health_check,
        tester.test_metrics,
        tester.test_bot_registration,
        tester.test_bot_heartbeat,
        tester.test_get_bots,
        tester.test_job_populate,
        tester.test_get_jobs,
        tester.test_job_claim,
        tester.test_job_workflow,
        tester.test_metrics_summary,
        tester.test_bot_deletion,
    ]
    
    # Run all tests
    results = []
    passed = 0
    failed = 0
    
    print("\n=== Running Tests ===")
    for test_func in tests:
        try:
            result = await test_func()
            results.append(result)
            
            status_icon = "PASS" if result["success"] else "FAIL"
            print(f"{status_icon}: {result['test']} (HTTP {result['status']})")
            
            if result["success"]:
                passed += 1
            else:
                failed += 1
                print(f"  Details: {result['details']}")
                
        except Exception as e:
            print(f"FAIL: {test_func.__name__} - Exception: {e}")
            failed += 1
            results.append({
                "test": test_func.__name__,
                "success": False,
                "status": 0,
                "details": f"Exception: {e}"
            })
    
    # Print summary
    total = passed + failed
    success_rate = (passed / total * 100) if total > 0 else 0
    
    print("\n=== Test Summary ===")
    print(f"Total Tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {success_rate:.1f}%")
    
    if failed > 0:
        print("\n=== Failed Tests ===")
        for result in results:
            if not result["success"]:
                print(f"- {result['test']}: {result['details']}")
    
    print("\n=== Detailed Results ===")
    for result in results:
        print(f"{result['test']}: {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    try:
        asyncio.run(run_comprehensive_tests())
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
    except Exception as e:
        print(f"Test suite failed: {e}")
        sys.exit(1)