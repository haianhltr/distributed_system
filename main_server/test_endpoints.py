#!/usr/bin/env python3
"""
Comprehensive test suite for distributed system endpoints.
Tests all major API endpoints to ensure proper functionality.
"""

import asyncio
import json
import uuid
import time
from typing import Dict, Any, List
import aiohttp
import pytest
from datetime import datetime


class TestConfig:
    BASE_URL = "http://localhost:3001"
    ADMIN_TOKEN = "admin-secret-token"
    TIMEOUT = 10


class APITester:
    def __init__(self):
        self.base_url = TestConfig.BASE_URL
        self.admin_headers = {"Authorization": f"Bearer {TestConfig.ADMIN_TOKEN}"}
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TestConfig.TIMEOUT))
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            
    async def request(self, method: str, endpoint: str, data: Dict = None, headers: Dict = None) -> Dict[str, Any]:
        """Make HTTP request to API endpoint"""
        url = f"{self.base_url}{endpoint}"
        request_headers = headers or {}
        
        async with self.session.request(method, url, json=data, headers=request_headers) as response:
            result = {
                "status": response.status,
                "headers": dict(response.headers),
                "url": str(response.url)
            }
            
            try:
                result["data"] = await response.json()
            except:
                result["data"] = await response.text()
                
            return result


class EndpointTests:
    def __init__(self, tester: APITester):
        self.tester = tester
        self.test_bot_id = f"test-bot-{int(time.time())}"
        self.test_job_ids = []
        
    async def test_health_check(self) -> Dict[str, Any]:
        """Test health check endpoint"""
        print(">>> Testing health check...")
        result = await self.tester.request("GET", "/healthz")
        
        success = result["status"] == 200
        print(f">>> Health check: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "health_check",
            "success": success,
            "status": result["status"],
            "response": result["data"]
        }
        
    async def test_bot_registration(self) -> Dict[str, Any]:
        """Test bot registration endpoint"""
        print(">>> Testing bot registration...")
        
        data = {"bot_id": self.test_bot_id}
        result = await self.tester.request("POST", "/bots/register", data)
        
        success = result["status"] == 200
        print(f">>> Bot registration: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "bot_registration", 
            "success": success,
            "status": result["status"],
            "response": result["data"],
            "bot_id": self.test_bot_id
        }
        
    async def test_bot_heartbeat(self) -> Dict[str, Any]:
        """Test bot heartbeat endpoint"""
        print(">>> Testing bot heartbeat...")
        
        data = {"bot_id": self.test_bot_id}
        result = await self.tester.request("POST", "/bots/heartbeat", data)
        
        success = result["status"] == 200
        print(f">>> Bot heartbeat: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "bot_heartbeat",
            "success": success, 
            "status": result["status"],
            "response": result["data"]
        }
        
    async def test_get_bots(self) -> Dict[str, Any]:
        """Test get all bots endpoint"""
        print(">>>� Testing get bots...")
        
        result = await self.tester.request("GET", "/bots")
        
        success = result["status"] == 200
        bot_found = False
        if success and isinstance(result["data"], list):
            bot_found = any(bot.get("id") == self.test_bot_id for bot in result["data"])
            
        print(f">>> Get bots: {'PASS' if success else 'FAIL'} (Status: {result['status']}, Bot found: {bot_found})")
        
        return {
            "test": "get_bots",
            "success": success,
            "status": result["status"],
            "bot_found": bot_found,
            "response": result["data"]
        }
        
    async def test_job_populate(self) -> Dict[str, Any]:
        """Test job population endpoint"""
        print(">>>� Testing job population...")
        
        data = {"batchSize": 3}
        result = await self.tester.request("POST", "/jobs/populate", data, self.tester.admin_headers)
        
        success = result["status"] in [200, 201]
        print(f">>> Job populate: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "job_populate",
            "success": success,
            "status": result["status"],
            "response": result["data"]
        }
        
    async def test_get_jobs(self) -> Dict[str, Any]:
        """Test get jobs endpoint"""
        print(">>>� Testing get jobs...")
        
        result = await self.tester.request("GET", "/jobs?limit=10")
        
        success = result["status"] == 200
        job_count = 0
        if success and isinstance(result["data"], list):
            job_count = len(result["data"])
            # Store job IDs for later tests
            self.test_job_ids = [job.get("id") for job in result["data"] if job.get("id")]
            
        print(f">>> Get jobs: {'PASS' if success else 'FAIL'} (Status: {result['status']}, Jobs: {job_count})")
        
        return {
            "test": "get_jobs",
            "success": success,
            "status": result["status"],
            "job_count": job_count,
            "response": result["data"]
        }
        
    async def test_job_claim(self) -> Dict[str, Any]:
        """Test job claiming endpoint"""
        print(">>>� Testing job claim...")
        
        data = {"bot_id": self.test_bot_id}
        result = await self.tester.request("POST", "/jobs/claim", data)
        
        success = result["status"] in [200, 204]  # 204 = no jobs available
        claimed_job_id = None
        
        if result["status"] == 200 and isinstance(result["data"], dict):
            claimed_job_id = result["data"].get("id")
            
        print(f">>> Job claim: {'PASS' if success else 'FAIL'} (Status: {result['status']}, Job: {claimed_job_id})")
        
        return {
            "test": "job_claim",
            "success": success,
            "status": result["status"],
            "claimed_job_id": claimed_job_id,
            "response": result["data"]
        }
        
    async def test_job_start(self, job_id: str) -> Dict[str, Any]:
        """Test job start endpoint"""
        if not job_id:
            return {"test": "job_start", "success": False, "error": "No job ID provided"}
            
        print(f">>>� Testing job start for {job_id[:8]}...")
        
        data = {"bot_id": self.test_bot_id}
        result = await self.tester.request("POST", f"/jobs/{job_id}/start", data)
        
        success = result["status"] == 200
        print(f">>> Job start: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "job_start",
            "success": success,
            "status": result["status"],
            "job_id": job_id,
            "response": result["data"]
        }
        
    async def test_job_complete(self, job_id: str) -> Dict[str, Any]:
        """Test job completion endpoint"""
        if not job_id:
            return {"test": "job_complete", "success": False, "error": "No job ID provided"}
            
        print(f">>> Testing job complete for {job_id[:8]}...")
        
        # Simulate completing a simple addition job
        data = {
            "bot_id": self.test_bot_id,
            "sum": 42,  # Dummy result
            "duration_ms": 1500
        }
        result = await self.tester.request("POST", f"/jobs/{job_id}/complete", data)
        
        success = result["status"] == 200
        print(f">>> Job complete: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "job_complete",
            "success": success,
            "status": result["status"],
            "job_id": job_id,
            "response": result["data"]
        }
        
    async def test_metrics_endpoint(self) -> Dict[str, Any]:
        """Test Prometheus metrics endpoint"""
        print(">>>� Testing metrics endpoint...")
        
        result = await self.tester.request("GET", "/metrics")
        
        success = result["status"] == 200
        has_metrics = False
        if success and isinstance(result["data"], str):
            # Check for some expected metric names
            has_metrics = any(metric in result["data"] for metric in 
                            ["job_total_created", "bot_active_count", "api_request_total"])
            
        print(f">>> Metrics: {'PASS' if success else 'FAIL'} (Status: {result['status']}, Has metrics: {has_metrics})")
        
        return {
            "test": "metrics_endpoint",
            "success": success,
            "status": result["status"],
            "has_metrics": has_metrics,
            "response": result["data"][:200] if isinstance(result["data"], str) else result["data"]
        }
        
    async def test_bot_deletion(self) -> Dict[str, Any]:
        """Test bot deletion endpoint"""
        print(">>>�>>> Testing bot deletion...")
        
        result = await self.tester.request("DELETE", f"/bots/{self.test_bot_id}", headers=self.tester.admin_headers)
        
        success = result["status"] == 200
        print(f">>> Bot deletion: {'PASS' if success else 'FAIL'} (Status: {result['status']})")
        
        return {
            "test": "bot_deletion",
            "success": success,
            "status": result["status"],
            "response": result["data"]
        }


async def run_comprehensive_tests():
    """Run all endpoint tests and generate a report"""
    print(">>>� Starting comprehensive endpoint tests...")
    print("=" * 60)
    
    start_time = time.time()
    test_results = []
    
    async with APITester() as tester:
        tests = EndpointTests(tester)
        
        # Core functionality tests
        test_results.append(await tests.test_health_check())
        test_results.append(await tests.test_bot_registration())
        test_results.append(await tests.test_bot_heartbeat())
        test_results.append(await tests.test_get_bots())
        
        # Job management tests
        test_results.append(await tests.test_job_populate())
        test_results.append(await tests.test_get_jobs())
        
        # Job workflow tests
        claim_result = await tests.test_job_claim()
        test_results.append(claim_result)
        
        claimed_job_id = claim_result.get("claimed_job_id")
        if claimed_job_id:
            start_result = await tests.test_job_start(claimed_job_id)
            test_results.append(start_result)
            
            if start_result.get("success"):
                test_results.append(await tests.test_job_complete(claimed_job_id))
        
        # System endpoints
        test_results.append(await tests.test_metrics_endpoint())
        
        # Cleanup
        test_results.append(await tests.test_bot_deletion())
    
    # Generate test report
    print("\n" + "=" * 60)
    print(">>>� TEST RESULTS SUMMARY")
    print("=" * 60)
    
    total_tests = len(test_results)
    passed_tests = sum(1 for result in test_results if result.get("success", False))
    failed_tests = total_tests - passed_tests
    
    print(f"Total Tests: {total_tests}")
    print(f">>> Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f">>>� Success Rate: {(passed_tests/total_tests)*100:.1f}%")
    print(f"⏱>>> Duration: {time.time() - start_time:.2f}s")
    
    # Detailed results
    print("\n>>>� DETAILED RESULTS:")
    for result in test_results:
        status = ">>> PASS" if result.get("success") else "❌ FAIL"
        test_name = result.get("test", "unknown").replace("_", " ").title()
        http_status = result.get("status", "N/A")
        print(f"  {status} | {test_name:<20} | HTTP {http_status}")
        
        if not result.get("success") and "response" in result:
            error_msg = str(result["response"])[:100]
            print(f"    Error: {error_msg}")
    
    # Failed test details
    failed_results = [r for r in test_results if not r.get("success")]
    if failed_results:
        print(f"\n❌ FAILED TESTS DETAILS:")
        for result in failed_results:
            print(f"\n• {result.get('test', 'unknown').replace('_', ' ').title()}:")
            print(f"  Status: {result.get('status', 'N/A')}")
            if "response" in result:
                print(f"  Response: {json.dumps(result['response'], indent=2)[:300]}")
    
    # Generate JSON report
    report = {
        "summary": {
            "total_tests": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "success_rate": (passed_tests/total_tests)*100,
            "duration": time.time() - start_time,
            "timestamp": datetime.utcnow().isoformat()
        },
        "results": test_results
    }
    
    # Save report
    with open("test_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"\n>>>� Full report saved to: test_report.json")
    
    return report


if __name__ == "__main__":
    print(">>> Distributed System API Test Suite")
    print(f"Target: {TestConfig.BASE_URL}")
    print("Starting tests in 3 seconds...")
    time.sleep(3)
    
    try:
        asyncio.run(run_comprehensive_tests())
    except KeyboardInterrupt:
        print("\n>>> Tests interrupted by user")
    except Exception as e:
        print(f"\n>>> Test suite failed: {e}")
        import traceback
        traceback.print_exc()