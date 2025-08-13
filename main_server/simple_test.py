#!/usr/bin/env python3
"""
Simple endpoint test to check which database endpoints are working
"""

import asyncio
import aiohttp
import time


class SimpleAPITest:
    def __init__(self):
        self.base_url = "http://localhost:3001"
        self.admin_headers = {"Authorization": "Bearer admin-secret-token"}
        self.test_bot_id = f"test-bot-{int(time.time())}"
        
    async def test_endpoint(self, method: str, endpoint: str, data=None, headers=None):
        """Test a single endpoint"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}{endpoint}"
                async with session.request(method, url, json=data, headers=headers) as response:
                    status = response.status
                    try:
                        response_data = await response.json()
                    except:
                        response_data = await response.text()
                    
                    return {
                        "endpoint": endpoint,
                        "method": method,
                        "status": status,
                        "success": status < 400,
                        "response": response_data
                    }
        except Exception as e:
            return {
                "endpoint": endpoint,
                "method": method, 
                "status": "ERROR",
                "success": False,
                "error": str(e)
            }

    async def run_tests(self):
        """Run basic endpoint tests"""
        print("=== API Endpoint Tests ===")
        
        tests = [
            # Basic endpoints
            ("GET", "/healthz", None, None),
            ("GET", "/metrics", None, None),
            
            # Bot endpoints
            ("POST", "/bots/register", {"bot_id": self.test_bot_id}, None),
            ("POST", "/bots/heartbeat", {"bot_id": self.test_bot_id}, None),
            ("GET", "/bots", None, None),
            
            # Job endpoints
            ("POST", "/jobs/populate", {"batchSize": 2}, self.admin_headers),
            ("GET", "/jobs?limit=5", None, None),
            ("POST", "/jobs/claim", {"bot_id": self.test_bot_id}, None),
            
            # Cleanup
            ("DELETE", f"/bots/{self.test_bot_id}", None, self.admin_headers),
        ]
        
        results = []
        for method, endpoint, data, headers in tests:
            print(f"Testing {method} {endpoint}...")
            result = await self.test_endpoint(method, endpoint, data, headers)
            results.append(result)
            
            status_emoji = "PASS" if result["success"] else "FAIL"
            print(f"  {status_emoji} {result['status']} - {result.get('error', 'OK')}")
            
            # Small delay between requests
            await asyncio.sleep(0.5)
        
        # Summary
        print("\n=== RESULTS SUMMARY ===")
        passed = sum(1 for r in results if r["success"])
        total = len(results)
        
        print(f"Passed: {passed}/{total}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        # Failed tests
        failed = [r for r in results if not r["success"]]
        if failed:
            print("\nFAILED TESTS:")
            for result in failed:
                print(f"  {result['method']} {result['endpoint']} - {result['status']}")
                if "error" in result:
                    print(f"    Error: {result['error']}")
                elif "response" in result:
                    error_text = str(result["response"])[:100]
                    print(f"    Response: {error_text}")
        
        return results


async def main():
    print("Starting API tests...")
    print("Target: http://localhost:3001")
    
    tester = SimpleAPITest()
    await tester.run_tests()


if __name__ == "__main__":
    asyncio.run(main())