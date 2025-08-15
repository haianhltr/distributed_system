"""
Load Testing and Race Condition Testing for Distributed System

This module provides comprehensive load testing tools specifically designed
to test race conditions and concurrent access patterns in job claiming systems.
"""

import asyncio
import time
import random
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict, Counter
import aiohttp
import asyncpg
import statistics

logger = logging.getLogger(__name__)


@dataclass
class LoadTestResult:
    """Results from a load test run"""
    test_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    duration_seconds: float
    requests_per_second: float
    average_response_time: float
    p95_response_time: float
    p99_response_time: float
    errors: Dict[str, int]
    race_condition_detected: bool
    consistency_violations: List[str]


@dataclass
class ConcurrentBot:
    """Represents a bot in load testing"""
    bot_id: str
    session: aiohttp.ClientSession
    claimed_jobs: List[str]
    failed_attempts: int
    total_attempts: int
    response_times: List[float]


class RaceConditionTester:
    """Test for race conditions in job claiming system"""
    
    def __init__(self, main_server_url: str, database_url: str, admin_token: str):
        self.main_server_url = main_server_url
        self.database_url = database_url
        self.admin_token = admin_token
        self.test_results = []
        
    async def stress_test_job_claiming(self, num_bots: int = 100, duration_seconds: int = 60) -> LoadTestResult:
        """Test job claiming under high concurrency to detect race conditions"""
        logger.info(f"Starting job claiming stress test: {num_bots} bots for {duration_seconds}s")
        
        # Prepare jobs for testing
        await self._prepare_test_jobs(num_bots * 2)  # More jobs than bots
        
        start_time = time.time()
        bots = []
        
        # Create concurrent bots
        for i in range(num_bots):
            session = aiohttp.ClientSession()
            bot = ConcurrentBot(
                bot_id=f"stress-test-bot-{i:03d}",
                session=session,
                claimed_jobs=[],
                failed_attempts=0,
                total_attempts=0,
                response_times=[]
            )
            bots.append(bot)
            
        try:
            # Register all bots
            await self._register_bots(bots)
            
            # Start concurrent job claiming
            tasks = []
            for bot in bots:
                task = asyncio.create_task(
                    self._bot_claim_jobs_continuously(bot, duration_seconds)
                )
                tasks.append(task)
                
            # Wait for all bots to finish
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Analyze results
            end_time = time.time()
            test_duration = end_time - start_time
            
            return await self._analyze_stress_test_results(bots, test_duration)
            
        finally:
            # Cleanup
            await self._cleanup_bots(bots)
            
    async def test_simultaneous_job_claims(self, num_bots: int = 50) -> LoadTestResult:
        """Test many bots claiming jobs at exactly the same time"""
        logger.info(f"Testing simultaneous job claims with {num_bots} bots")
        
        # Create exactly one job for multiple bots to fight over
        await self._prepare_test_jobs(1)
        
        bots = []
        for i in range(num_bots):
            session = aiohttp.ClientSession()
            bot = ConcurrentBot(
                bot_id=f"race-test-bot-{i:03d}",
                session=session,
                claimed_jobs=[],
                failed_attempts=0,
                total_attempts=0,
                response_times=[]
            )
            bots.append(bot)
            
        try:
            await self._register_bots(bots)
            
            # All bots try to claim the same job simultaneously
            start_time = time.time()
            tasks = []
            
            for bot in bots:
                task = asyncio.create_task(self._claim_single_job(bot))
                tasks.append(task)
                
            # Execute all claims simultaneously
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            # Count successful claims
            successful_claims = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
            
            # Verify only one bot got the job
            race_condition_detected = successful_claims != 1
            
            if race_condition_detected:
                logger.error(f"RACE CONDITION: {successful_claims} bots claimed the same job!")
            else:
                logger.info("No race condition detected - exactly 1 bot claimed the job")
                
            return LoadTestResult(
                test_name="simultaneous_job_claims",
                total_requests=num_bots,
                successful_requests=successful_claims,
                failed_requests=num_bots - successful_claims,
                duration_seconds=end_time - start_time,
                requests_per_second=num_bots / (end_time - start_time),
                average_response_time=0,  # Will calculate from bot data
                p95_response_time=0,
                p99_response_time=0,
                errors={},
                race_condition_detected=race_condition_detected,
                consistency_violations=[]
            )
            
        finally:
            await self._cleanup_bots(bots)
            
    async def test_job_claiming_under_database_stress(self, num_bots: int = 20) -> LoadTestResult:
        """Test job claiming while database is under stress"""
        logger.info(f"Testing job claiming under database stress with {num_bots} bots")
        
        # Start database stress in background
        stress_task = asyncio.create_task(self._create_database_stress())
        
        try:
            # Run normal job claiming test
            result = await self.stress_test_job_claiming(num_bots, duration_seconds=30)
            result.test_name = "job_claiming_under_db_stress"
            return result
        finally:
            stress_task.cancel()
            
    async def _prepare_test_jobs(self, num_jobs: int):
        """Create jobs for testing"""
        jobs = {"batchSize": num_jobs}
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            async with session.post(
                f"{self.main_server_url}/jobs/populate",
                json=jobs,
                headers=headers
            ) as response:
                if response.status != 200:
                    raise Exception(f"Failed to create test jobs: {response.status}")
                    
    async def _register_bots(self, bots: List[ConcurrentBot]):
        """Register all test bots"""
        tasks = []
        for bot in bots:
            task = asyncio.create_task(self._register_single_bot(bot))
            tasks.append(task)
            
        await asyncio.gather(*tasks, return_exceptions=True)
        
    async def _register_single_bot(self, bot: ConcurrentBot):
        """Register a single bot"""
        try:
            async with bot.session.post(
                f"{self.main_server_url}/bots/register",
                json={"bot_id": bot.bot_id}
            ) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Failed to register bot {bot.bot_id}: {e}")
            return False
            
    async def _bot_claim_jobs_continuously(self, bot: ConcurrentBot, duration_seconds: int):
        """Bot continuously claims jobs for specified duration"""
        end_time = time.time() + duration_seconds
        
        while time.time() < end_time:
            try:
                success = await self._claim_single_job(bot)
                
                if success:
                    # Process the job briefly
                    await asyncio.sleep(random.uniform(0.1, 0.5))
                    # Complete the job (simplified)
                    await self._complete_last_job(bot)
                else:
                    # Brief backoff on failure
                    await asyncio.sleep(random.uniform(0.01, 0.1))
                    
            except Exception as e:
                logger.error(f"Bot {bot.bot_id} error: {e}")
                await asyncio.sleep(0.1)
                
    async def _claim_single_job(self, bot: ConcurrentBot) -> bool:
        """Attempt to claim a single job"""
        bot.total_attempts += 1
        start_time = time.time()
        
        try:
            async with bot.session.post(
                f"{self.main_server_url}/jobs/claim",
                json={"bot_id": bot.bot_id}
            ) as response:
                response_time = time.time() - start_time
                bot.response_times.append(response_time)
                
                if response.status == 200:
                    job_data = await response.json()
                    bot.claimed_jobs.append(job_data.get('id'))
                    return True
                else:
                    bot.failed_attempts += 1
                    return False
                    
        except Exception as e:
            bot.failed_attempts += 1
            bot.response_times.append(time.time() - start_time)
            return False
            
    async def _complete_last_job(self, bot: ConcurrentBot):
        """Complete the last claimed job"""
        if not bot.claimed_jobs:
            return
            
        job_id = bot.claimed_jobs[-1]
        
        try:
            # Start job
            async with bot.session.post(
                f"{self.main_server_url}/jobs/{job_id}/start",
                json={"bot_id": bot.bot_id}
            ) as response:
                pass
                
            # Complete job
            async with bot.session.post(
                f"{self.main_server_url}/jobs/{job_id}/complete",
                json={
                    "bot_id": bot.bot_id,
                    "result": 42,  # Dummy result
                    "duration_ms": 100
                }
            ) as response:
                pass
                
        except Exception as e:
            logger.error(f"Failed to complete job {job_id}: {e}")
            
    async def _cleanup_bots(self, bots: List[ConcurrentBot]):
        """Cleanup test bots"""
        tasks = []
        for bot in bots:
            task = asyncio.create_task(self._cleanup_single_bot(bot))
            tasks.append(task)
            
        await asyncio.gather(*tasks, return_exceptions=True)
        
    async def _cleanup_single_bot(self, bot: ConcurrentBot):
        """Cleanup a single bot"""
        try:
            # Delete bot
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            async with bot.session.delete(
                f"{self.main_server_url}/bots/{bot.bot_id}",
                headers=headers
            ) as response:
                pass
                
        except Exception as e:
            logger.error(f"Failed to cleanup bot {bot.bot_id}: {e}")
        finally:
            await bot.session.close()
            
    async def _analyze_stress_test_results(self, bots: List[ConcurrentBot], duration: float) -> LoadTestResult:
        """Analyze the results of stress testing"""
        total_requests = sum(bot.total_attempts for bot in bots)
        successful_requests = sum(len(bot.claimed_jobs) for bot in bots)
        failed_requests = sum(bot.failed_attempts for bot in bots)
        
        all_response_times = []
        for bot in bots:
            all_response_times.extend(bot.response_times)
            
        # Calculate response time statistics
        avg_response_time = statistics.mean(all_response_times) if all_response_times else 0
        p95_response_time = statistics.quantiles(all_response_times, n=20)[18] if len(all_response_times) >= 20 else 0
        p99_response_time = statistics.quantiles(all_response_times, n=100)[98] if len(all_response_times) >= 100 else 0
        
        # Check for consistency violations
        consistency_violations = await self._check_consistency_violations()
        race_condition_detected = len(consistency_violations) > 0
        
        return LoadTestResult(
            test_name="stress_test_job_claiming",
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            duration_seconds=duration,
            requests_per_second=total_requests / duration if duration > 0 else 0,
            average_response_time=avg_response_time,
            p95_response_time=p95_response_time,
            p99_response_time=p99_response_time,
            errors={},
            race_condition_detected=race_condition_detected,
            consistency_violations=consistency_violations
        )
        
    async def _check_consistency_violations(self) -> List[str]:
        """Check for data consistency violations"""
        violations = []
        
        try:
            async with asyncpg.connect(self.database_url) as conn:
                # Check for duplicate job assignments
                duplicates = await conn.fetch("""
                    SELECT current_job_id, COUNT(*) as count
                    FROM bots 
                    WHERE current_job_id IS NOT NULL
                    GROUP BY current_job_id
                    HAVING COUNT(*) > 1
                """)
                
                for dup in duplicates:
                    violations.append(f"Job {dup['current_job_id']} assigned to {dup['count']} bots")
                    
                # Check for orphaned job assignments
                orphaned = await conn.fetch("""
                    SELECT b.id, b.current_job_id
                    FROM bots b
                    LEFT JOIN jobs j ON b.current_job_id = j.id
                    WHERE b.current_job_id IS NOT NULL 
                    AND j.id IS NULL
                """)
                
                for orphan in orphaned:
                    violations.append(f"Bot {orphan['id']} has non-existent job {orphan['current_job_id']}")
                    
        except Exception as e:
            violations.append(f"Failed to check consistency: {e}")
            
        return violations
        
    async def _create_database_stress(self):
        """Create stress on database during testing"""
        try:
            async with asyncpg.connect(self.database_url) as conn:
                while True:
                    # Create some stress with heavy queries
                    await conn.fetch("SELECT COUNT(*) FROM jobs")
                    await conn.fetch("SELECT COUNT(*) FROM bots")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Database stress error: {e}")


class LoadTestSuite:
    """Complete suite of load tests"""
    
    def __init__(self, main_server_url: str, database_url: str, admin_token: str):
        self.race_tester = RaceConditionTester(main_server_url, database_url, admin_token)
        self.results = []
        
    async def run_all_tests(self) -> List[LoadTestResult]:
        """Run complete load test suite"""
        logger.info("Starting complete load test suite")
        
        tests = [
            ("Basic Race Condition Test", self.race_tester.test_simultaneous_job_claims(50)),
            ("Light Load Test", self.race_tester.stress_test_job_claiming(10, 30)),
            ("Medium Load Test", self.race_tester.stress_test_job_claiming(25, 60)),
            ("Heavy Load Test", self.race_tester.stress_test_job_claiming(50, 60)),
            ("Database Stress Test", self.race_tester.test_job_claiming_under_database_stress(20)),
        ]
        
        for test_name, test_coro in tests:
            logger.info(f"Running: {test_name}")
            try:
                result = await test_coro
                result.test_name = test_name
                self.results.append(result)
                
                # Brief pause between tests
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Test {test_name} failed: {e}")
                
        return self.results
        
    def generate_load_test_report(self) -> Dict[str, Any]:
        """Generate comprehensive load test report"""
        if not self.results:
            return {"error": "No test results available"}
            
        report = {
            "summary": {
                "total_tests": len(self.results),
                "tests_with_race_conditions": sum(1 for r in self.results if r.race_condition_detected),
                "average_requests_per_second": statistics.mean([r.requests_per_second for r in self.results]),
                "total_requests_tested": sum(r.total_requests for r in self.results),
                "overall_success_rate": sum(r.successful_requests for r in self.results) / sum(r.total_requests for r in self.results)
            },
            "test_results": [],
            "recommendations": self._generate_load_test_recommendations()
        }
        
        for result in self.results:
            report["test_results"].append({
                "test_name": result.test_name,
                "requests_per_second": result.requests_per_second,
                "success_rate": result.successful_requests / result.total_requests if result.total_requests > 0 else 0,
                "average_response_time_ms": result.average_response_time * 1000,
                "p95_response_time_ms": result.p95_response_time * 1000,
                "race_condition_detected": result.race_condition_detected,
                "consistency_violations": result.consistency_violations
            })
            
        return report
        
    def _generate_load_test_recommendations(self) -> List[str]:
        """Generate recommendations based on load test results"""
        recommendations = []
        
        # Check for race conditions
        race_condition_tests = [r for r in self.results if r.race_condition_detected]
        if race_condition_tests:
            recommendations.append("CRITICAL: Race conditions detected! Implement proper database locking")
            recommendations.append("Use PostgreSQL's FOR UPDATE SKIP LOCKED for atomic job claiming")
            
        # Check response times
        slow_tests = [r for r in self.results if r.average_response_time > 1.0]
        if slow_tests:
            recommendations.append("High response times detected - consider connection pooling optimization")
            
        # Check success rates
        low_success_tests = [r for r in self.results if (r.successful_requests / r.total_requests) < 0.8]
        if low_success_tests:
            recommendations.append("Low success rates detected - implement better error handling and retries")
            
        recommendations.extend([
            "Monitor database connection pool size under load",
            "Implement circuit breakers for graceful degradation",
            "Add database query timeouts to prevent hanging connections",
            "Consider horizontal scaling if throughput is insufficient"
        ])
        
        return recommendations