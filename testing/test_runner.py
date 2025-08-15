"""
Test Runner for Chaos Engineering and Load Testing

This module provides a unified interface to run chaos engineering
and load testing experiments on the distributed system.
"""

import asyncio
import argparse
import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, List
import sys

# Add the testing directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chaos_monkey import ChaosMonkey, ChaosExperiments
from load_tester import LoadTestSuite, RaceConditionTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRunner:
    """Main test runner for chaos and load testing"""
    
    def __init__(self, config: Dict[str, str]):
        self.config = config
        self.chaos_monkey = ChaosMonkey(
            database_url=config['database_url'],
            main_server_url=config['main_server_url']
        )
        self.chaos_experiments = ChaosExperiments(self.chaos_monkey)
        self.load_test_suite = LoadTestSuite(
            main_server_url=config['main_server_url'],
            database_url=config['database_url'],
            admin_token=config['admin_token']
        )
        
    async def run_chaos_tests(self) -> Dict[str, Any]:
        """Run all chaos engineering tests"""
        logger.info("Starting chaos engineering tests")
        
        results = {
            "start_time": datetime.now().isoformat(),
            "tests": []
        }
        
        # Test 1: Database resilience
        try:
            logger.info("Running database resilience test")
            db_result = await self.chaos_experiments.test_database_resilience()
            results["tests"].append(db_result)
        except Exception as e:
            logger.error(f"Database resilience test failed: {e}")
            results["tests"].append({
                "experiment": "database_resilience",
                "error": str(e),
                "passed": False
            })
            
        # Test 2: Network partition recovery
        try:
            logger.info("Running network partition recovery test")
            net_result = await self.chaos_experiments.test_network_partition_recovery()
            results["tests"].append(net_result)
        except Exception as e:
            logger.error(f"Network partition test failed: {e}")
            results["tests"].append({
                "experiment": "network_partition_recovery",
                "error": str(e),
                "passed": False
            })
            
        # Test 3: Full chaos session
        try:
            logger.info("Running full chaos session")
            await self.chaos_monkey.start_chaos_session(duration_seconds=120)
            chaos_report = self.chaos_monkey.generate_chaos_report()
            results["chaos_report"] = chaos_report
        except Exception as e:
            logger.error(f"Chaos session failed: {e}")
            results["chaos_session_error"] = str(e)
            
        results["end_time"] = datetime.now().isoformat()
        return results
        
    async def run_load_tests(self) -> Dict[str, Any]:
        """Run all load tests"""
        logger.info("Starting load tests")
        
        # Run the complete load test suite
        test_results = await self.load_test_suite.run_all_tests()
        
        # Generate comprehensive report
        report = self.load_test_suite.generate_load_test_report()
        
        return {
            "start_time": datetime.now().isoformat(),
            "load_test_report": report,
            "detailed_results": [
                {
                    "test_name": r.test_name,
                    "total_requests": r.total_requests,
                    "successful_requests": r.successful_requests,
                    "failed_requests": r.failed_requests,
                    "duration_seconds": r.duration_seconds,
                    "requests_per_second": r.requests_per_second,
                    "average_response_time_ms": r.average_response_time * 1000,
                    "p95_response_time_ms": r.p95_response_time * 1000,
                    "p99_response_time_ms": r.p99_response_time * 1000,
                    "race_condition_detected": r.race_condition_detected,
                    "consistency_violations": r.consistency_violations
                }
                for r in test_results
            ]
        }
        
    async def run_quick_race_condition_test(self) -> Dict[str, Any]:
        """Run a quick race condition test"""
        logger.info("Running quick race condition test")
        
        race_tester = RaceConditionTester(
            main_server_url=self.config['main_server_url'],
            database_url=self.config['database_url'],
            admin_token=self.config['admin_token']
        )
        
        result = await race_tester.test_simultaneous_job_claims(num_bots=20)
        
        return {
            "test_type": "quick_race_condition",
            "result": {
                "race_condition_detected": result.race_condition_detected,
                "total_requests": result.total_requests,
                "successful_requests": result.successful_requests,
                "consistency_violations": result.consistency_violations,
                "requests_per_second": result.requests_per_second
            },
            "passed": not result.race_condition_detected,
            "timestamp": datetime.now().isoformat()
        }
        
    async def run_system_health_check(self) -> Dict[str, Any]:
        """Run comprehensive system health check"""
        logger.info("Running system health check")
        
        health = await self.chaos_monkey.measure_system_health()
        
        # Add additional checks
        consistency_check = await self._detailed_consistency_check()
        health["detailed_consistency"] = consistency_check
        
        return health
        
    async def _detailed_consistency_check(self) -> Dict[str, Any]:
        """Perform detailed consistency checking"""
        import asyncpg
        
        try:
            async with asyncpg.connect(self.config['database_url']) as conn:
                # Check for various consistency issues
                checks = {}
                
                # 1. Bots with non-existent jobs
                orphaned_bots = await conn.fetch("""
                    SELECT b.id, b.current_job_id, b.status
                    FROM bots b
                    LEFT JOIN jobs j ON b.current_job_id = j.id
                    WHERE b.current_job_id IS NOT NULL 
                    AND j.id IS NULL
                    AND b.deleted_at IS NULL
                """)
                checks["orphaned_bots"] = [dict(r) for r in orphaned_bots]
                
                # 2. Jobs claimed by non-existent bots
                orphaned_jobs = await conn.fetch("""
                    SELECT j.id, j.status, j.claimed_by
                    FROM jobs j
                    LEFT JOIN bots b ON j.claimed_by = b.id
                    WHERE j.claimed_by IS NOT NULL 
                    AND b.id IS NULL
                """)
                checks["orphaned_jobs"] = [dict(r) for r in orphaned_jobs]
                
                # 3. Duplicate job assignments
                duplicate_assignments = await conn.fetch("""
                    SELECT current_job_id, array_agg(id) as bot_ids, COUNT(*) as count
                    FROM bots 
                    WHERE current_job_id IS NOT NULL
                    AND deleted_at IS NULL
                    GROUP BY current_job_id
                    HAVING COUNT(*) > 1
                """)
                checks["duplicate_assignments"] = [dict(r) for r in duplicate_assignments]
                
                # 4. Jobs in processing state with no active bot
                stale_processing_jobs = await conn.fetch("""
                    SELECT j.id, j.claimed_by, j.started_at
                    FROM jobs j
                    LEFT JOIN bots b ON j.claimed_by = b.id
                    WHERE j.status = 'processing'
                    AND (b.id IS NULL OR b.deleted_at IS NOT NULL)
                """)
                checks["stale_processing_jobs"] = [dict(r) for r in stale_processing_jobs]
                
                # 5. Long-running pending jobs
                old_pending_jobs = await conn.fetch("""
                    SELECT id, created_at, 
                           EXTRACT(EPOCH FROM (NOW() - created_at)) as age_seconds
                    FROM jobs 
                    WHERE status = 'pending'
                    AND created_at < NOW() - INTERVAL '30 minutes'
                    ORDER BY created_at ASC
                    LIMIT 10
                """)
                checks["old_pending_jobs"] = [dict(r) for r in old_pending_jobs]
                
                # Calculate overall health score
                total_issues = (
                    len(checks["orphaned_bots"]) +
                    len(checks["orphaned_jobs"]) +
                    len(checks["duplicate_assignments"]) +
                    len(checks["stale_processing_jobs"])
                )
                
                checks["health_score"] = max(0, 100 - (total_issues * 10))
                checks["status"] = "healthy" if total_issues == 0 else ("degraded" if total_issues < 5 else "unhealthy")
                
                return checks
                
        except Exception as e:
            return {
                "error": str(e),
                "status": "unknown"
            }
            
    def save_results(self, results: Dict[str, Any], filename: str):
        """Save test results to file"""
        os.makedirs("test_results", exist_ok=True)
        filepath = os.path.join("test_results", filename)
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        logger.info(f"Results saved to {filepath}")


async def main():
    """Main entry point for test runner"""
    parser = argparse.ArgumentParser(description="Run chaos engineering and load tests")
    parser.add_argument("--test-type", choices=["chaos", "load", "race", "health", "all"], 
                       default="all", help="Type of test to run")
    parser.add_argument("--database-url", default="postgresql://ds_user:ds_password@localhost:5432/distributed_system",
                       help="Database connection URL")
    parser.add_argument("--main-server-url", default="http://localhost:3001",
                       help="Main server URL")
    parser.add_argument("--admin-token", default="admin-secret-token",
                       help="Admin token for API access")
    parser.add_argument("--save-results", action="store_true",
                       help="Save results to files")
    
    args = parser.parse_args()
    
    config = {
        "database_url": args.database_url,
        "main_server_url": args.main_server_url,
        "admin_token": args.admin_token
    }
    
    runner = TestRunner(config)
    
    try:
        if args.test_type in ["chaos", "all"]:
            logger.info("=== CHAOS ENGINEERING TESTS ===")
            chaos_results = await runner.run_chaos_tests()
            print(json.dumps(chaos_results, indent=2, default=str))
            
            if args.save_results:
                runner.save_results(chaos_results, f"chaos_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                
        if args.test_type in ["load", "all"]:
            logger.info("=== LOAD TESTS ===")
            load_results = await runner.run_load_tests()
            print(json.dumps(load_results, indent=2, default=str))
            
            if args.save_results:
                runner.save_results(load_results, f"load_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                
        if args.test_type in ["race", "all"]:
            logger.info("=== RACE CONDITION TEST ===")
            race_results = await runner.run_quick_race_condition_test()
            print(json.dumps(race_results, indent=2, default=str))
            
            if args.save_results:
                runner.save_results(race_results, f"race_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                
        if args.test_type in ["health", "all"]:
            logger.info("=== SYSTEM HEALTH CHECK ===")
            health_results = await runner.run_system_health_check()
            print(json.dumps(health_results, indent=2, default=str))
            
            if args.save_results:
                runner.save_results(health_results, f"health_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise
    finally:
        # Cleanup
        await runner.chaos_monkey.stop_all_chaos()


if __name__ == "__main__":
    asyncio.run(main())