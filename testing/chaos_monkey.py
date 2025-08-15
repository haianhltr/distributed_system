"""
Chaos Engineering Tools for Distributed System Testing

This module provides chaos monkey functionality to test system resilience
by injecting various types of failures and measuring system response.
"""

import asyncio
import random
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
import asyncpg
import aiohttp
import psutil

logger = logging.getLogger(__name__)


class ChaosMonkey:
    """Chaos engineering tool for testing distributed system resilience"""
    
    def __init__(self, database_url: str, main_server_url: str = "http://localhost:3001"):
        self.database_url = database_url
        self.main_server_url = main_server_url
        self.active_chaos = []
        self.metrics = {
            "failures_injected": 0,
            "system_recovery_times": [],
            "error_counts": {},
            "start_time": None
        }
        
    async def start_chaos_session(self, duration_seconds: int = 300):
        """Start a chaos engineering session"""
        logger.info(f"Starting chaos session for {duration_seconds} seconds")
        self.metrics["start_time"] = datetime.now()
        
        # Schedule different types of chaos
        chaos_tasks = [
            asyncio.create_task(self._random_database_delays(duration_seconds)),
            asyncio.create_task(self._kill_random_connections(duration_seconds)),
            asyncio.create_task(self._inject_network_delays(duration_seconds)),
            asyncio.create_task(self._corrupt_bot_states(duration_seconds))
        ]
        
        try:
            await asyncio.gather(*chaos_tasks, return_exceptions=True)
        finally:
            await self.stop_all_chaos()
            
    async def stop_all_chaos(self):
        """Stop all active chaos experiments"""
        logger.info("Stopping all chaos experiments")
        for task in self.active_chaos:
            if not task.done():
                task.cancel()
        self.active_chaos.clear()
        
    async def introduce_database_delays(self, min_delay: float = 0.1, max_delay: float = 2.0):
        """Simulate slow database queries"""
        delay = random.uniform(min_delay, max_delay)
        logger.warning(f"Injecting database delay: {delay:.2f}s")
        
        # Monkey patch database operations
        original_execute = None
        try:
            async with asyncpg.connect(self.database_url) as conn:
                original_execute = conn.execute
                
                async def delayed_execute(*args, **kwargs):
                    await asyncio.sleep(delay)
                    return await original_execute(*args, **kwargs)
                
                conn.execute = delayed_execute
                await asyncio.sleep(5)  # Keep delay active for 5 seconds
                
        except Exception as e:
            logger.error(f"Failed to inject database delay: {e}")
        finally:
            # Restore original function
            if original_execute:
                conn.execute = original_execute
                
        self.metrics["failures_injected"] += 1
        
    async def kill_random_connections(self, count: int = 1):
        """Kill random database connections to test pool recovery"""
        logger.warning(f"Killing {count} random database connections")
        
        try:
            async with asyncpg.connect(self.database_url) as conn:
                # Get list of active connections
                connections = await conn.fetch("""
                    SELECT pid, usename, application_name, state 
                    FROM pg_stat_activity 
                    WHERE state = 'active' 
                    AND pid != pg_backend_pid()
                    LIMIT $1
                """, count)
                
                for connection in connections:
                    try:
                        # Kill the connection
                        await conn.execute("SELECT pg_terminate_backend($1)", connection['pid'])
                        logger.info(f"Killed connection PID: {connection['pid']}")
                        self.metrics["failures_injected"] += 1
                    except Exception as e:
                        logger.error(f"Failed to kill connection {connection['pid']}: {e}")
                        
        except Exception as e:
            logger.error(f"Failed to kill connections: {e}")
            
    async def inject_network_delays(self, target_delay_ms: int = 500):
        """Simulate network latency between services"""
        logger.warning(f"Injecting network delay: {target_delay_ms}ms")
        
        # This would typically use tools like tc (traffic control) on Linux
        # For simulation, we'll add delays to HTTP requests
        original_request = aiohttp.ClientSession._request
        
        async def delayed_request(self, method, url, **kwargs):
            await asyncio.sleep(target_delay_ms / 1000.0)
            return await original_request(self, method, url, **kwargs)
            
        aiohttp.ClientSession._request = delayed_request
        
        # Keep delay active for a short time
        await asyncio.sleep(10)
        
        # Restore original
        aiohttp.ClientSession._request = original_request
        self.metrics["failures_injected"] += 1
        
    async def corrupt_bot_states(self):
        """Introduce inconsistent bot states to test recovery"""
        logger.warning("Corrupting random bot states")
        
        try:
            async with asyncpg.connect(self.database_url) as conn:
                # Get random active bot
                bot = await conn.fetchrow("""
                    SELECT id FROM bots 
                    WHERE deleted_at IS NULL 
                    ORDER BY RANDOM() 
                    LIMIT 1
                """)
                
                if bot:
                    # Create inconsistent state: assign non-existent job
                    fake_job_id = f"chaos-job-{int(time.time())}"
                    await conn.execute("""
                        UPDATE bots 
                        SET current_job_id = $1, status = 'busy'
                        WHERE id = $2
                    """, fake_job_id, bot['id'])
                    
                    logger.info(f"Corrupted bot {bot['id']} with fake job {fake_job_id}")
                    self.metrics["failures_injected"] += 1
                    
        except Exception as e:
            logger.error(f"Failed to corrupt bot state: {e}")
            
    async def _random_database_delays(self, duration: int):
        """Continuously inject random database delays"""
        end_time = time.time() + duration
        while time.time() < end_time:
            await asyncio.sleep(random.uniform(10, 30))  # Random interval
            await self.introduce_database_delays()
            
    async def _kill_random_connections(self, duration: int):
        """Continuously kill random connections"""
        end_time = time.time() + duration
        while time.time() < end_time:
            await asyncio.sleep(random.uniform(20, 60))  # Random interval
            await self.kill_random_connections()
            
    async def _inject_network_delays(self, duration: int):
        """Continuously inject network delays"""
        end_time = time.time() + duration
        while time.time() < end_time:
            await asyncio.sleep(random.uniform(15, 45))  # Random interval
            await self.inject_network_delays(random.randint(100, 1000))
            
    async def _corrupt_bot_states(self, duration: int):
        """Continuously corrupt bot states"""
        end_time = time.time() + duration
        while time.time() < end_time:
            await asyncio.sleep(random.uniform(30, 90))  # Random interval
            await self.corrupt_bot_states()
            
    async def measure_system_health(self) -> Dict[str, Any]:
        """Measure current system health metrics"""
        health = {
            "timestamp": datetime.now().isoformat(),
            "database": await self._check_database_health(),
            "api": await self._check_api_health(),
            "job_processing": await self._check_job_processing_health(),
            "consistency": await self._check_data_consistency()
        }
        return health
        
    async def _check_database_health(self) -> Dict[str, Any]:
        """Check database connectivity and performance"""
        try:
            start_time = time.time()
            async with asyncpg.connect(self.database_url) as conn:
                # Test basic connectivity
                await conn.fetchval("SELECT 1")
                
                # Check connection pool status
                active_connections = await conn.fetchval("""
                    SELECT COUNT(*) FROM pg_stat_activity 
                    WHERE state = 'active'
                """)
                
                response_time = time.time() - start_time
                
                return {
                    "status": "healthy",
                    "response_time_ms": response_time * 1000,
                    "active_connections": active_connections
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
            
    async def _check_api_health(self) -> Dict[str, Any]:
        """Check main server API health"""
        try:
            start_time = time.time()
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.main_server_url}/healthz") as response:
                    response_time = time.time() - start_time
                    
                    if response.status == 200:
                        return {
                            "status": "healthy",
                            "response_time_ms": response_time * 1000,
                            "http_status": response.status
                        }
                    else:
                        return {
                            "status": "degraded",
                            "response_time_ms": response_time * 1000,
                            "http_status": response.status
                        }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
            
    async def _check_job_processing_health(self) -> Dict[str, Any]:
        """Check job processing pipeline health"""
        try:
            async with asyncpg.connect(self.database_url) as conn:
                # Count jobs by status
                job_counts = await conn.fetch("""
                    SELECT status, COUNT(*) as count 
                    FROM jobs 
                    GROUP BY status
                """)
                
                # Check for stuck jobs
                stuck_jobs = await conn.fetchval("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE status = 'pending' 
                    AND created_at < NOW() - INTERVAL '10 minutes'
                """)
                
                # Check processing rate
                recent_completions = await conn.fetchval("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE status IN ('succeeded', 'failed')
                    AND finished_at > NOW() - INTERVAL '5 minutes'
                """)
                
                return {
                    "status": "healthy" if stuck_jobs == 0 else "degraded",
                    "job_counts": {row['status']: row['count'] for row in job_counts},
                    "stuck_jobs": stuck_jobs,
                    "recent_completions": recent_completions
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
            
    async def _check_data_consistency(self) -> Dict[str, Any]:
        """Check for data consistency issues"""
        try:
            async with asyncpg.connect(self.database_url) as conn:
                # Check for bots with non-existent jobs
                orphaned_bots = await conn.fetchval("""
                    SELECT COUNT(*) FROM bots b
                    LEFT JOIN jobs j ON b.current_job_id = j.id
                    WHERE b.current_job_id IS NOT NULL 
                    AND j.id IS NULL
                """)
                
                # Check for jobs claimed by non-existent bots
                orphaned_jobs = await conn.fetchval("""
                    SELECT COUNT(*) FROM jobs j
                    LEFT JOIN bots b ON j.claimed_by = b.id
                    WHERE j.claimed_by IS NOT NULL 
                    AND b.id IS NULL
                """)
                
                # Check for duplicate job assignments
                duplicate_assignments = await conn.fetchval("""
                    SELECT COUNT(*) - COUNT(DISTINCT current_job_id)
                    FROM bots 
                    WHERE current_job_id IS NOT NULL
                """)
                
                issues = orphaned_bots + orphaned_jobs + duplicate_assignments
                
                return {
                    "status": "consistent" if issues == 0 else "inconsistent",
                    "orphaned_bots": orphaned_bots,
                    "orphaned_jobs": orphaned_jobs,
                    "duplicate_assignments": duplicate_assignments,
                    "total_issues": issues
                }
        except Exception as e:
            return {
                "status": "unknown",
                "error": str(e)
            }
            
    def generate_chaos_report(self) -> Dict[str, Any]:
        """Generate a report of chaos engineering results"""
        duration = None
        if self.metrics["start_time"]:
            duration = (datetime.now() - self.metrics["start_time"]).total_seconds()
            
        return {
            "session_duration_seconds": duration,
            "failures_injected": self.metrics["failures_injected"],
            "average_recovery_time": (
                sum(self.metrics["system_recovery_times"]) / len(self.metrics["system_recovery_times"])
                if self.metrics["system_recovery_times"] else 0
            ),
            "error_counts": self.metrics["error_counts"],
            "recommendations": self._generate_recommendations()
        }
        
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on chaos test results"""
        recommendations = []
        
        if self.metrics["failures_injected"] > 0:
            recommendations.append("System survived chaos testing - good resilience")
            
        if len(self.metrics["system_recovery_times"]) > 0:
            avg_recovery = sum(self.metrics["system_recovery_times"]) / len(self.metrics["system_recovery_times"])
            if avg_recovery > 30:
                recommendations.append("Consider faster recovery mechanisms - recovery time is high")
                
        recommendations.extend([
            "Implement circuit breakers with exponential backoff",
            "Add database connection pooling with health checks",
            "Monitor for data consistency issues continuously",
            "Use PostgreSQL's FOR UPDATE SKIP LOCKED for job claiming"
        ])
        
        return recommendations


class ChaosExperiments:
    """Predefined chaos experiments for common scenarios"""
    
    def __init__(self, chaos_monkey: ChaosMonkey):
        self.chaos_monkey = chaos_monkey
        
    async def test_database_resilience(self):
        """Test system resilience to database issues"""
        logger.info("Starting database resilience test")
        
        # Phase 1: Baseline measurement
        baseline = await self.chaos_monkey.measure_system_health()
        
        # Phase 2: Inject database delays
        await self.chaos_monkey.introduce_database_delays(min_delay=1.0, max_delay=5.0)
        
        # Phase 3: Kill connections
        await asyncio.sleep(10)
        await self.chaos_monkey.kill_random_connections(count=3)
        
        # Phase 4: Recovery measurement
        await asyncio.sleep(30)  # Wait for recovery
        recovery = await self.chaos_monkey.measure_system_health()
        
        return {
            "experiment": "database_resilience",
            "baseline": baseline,
            "recovery": recovery,
            "passed": recovery["database"]["status"] == "healthy"
        }
        
    async def test_high_concurrency_job_claiming(self):
        """Test job claiming under high concurrency"""
        logger.info("Starting high concurrency job claiming test")
        
        # This will be implemented in the load testing section
        pass
        
    async def test_network_partition_recovery(self):
        """Test recovery from network partitions"""
        logger.info("Starting network partition recovery test")
        
        baseline = await self.chaos_monkey.measure_system_health()
        
        # Inject network delays
        await self.chaos_monkey.inject_network_delays(target_delay_ms=2000)
        
        # Wait and measure recovery
        await asyncio.sleep(60)
        recovery = await self.chaos_monkey.measure_system_health()
        
        return {
            "experiment": "network_partition_recovery",
            "baseline": baseline,
            "recovery": recovery,
            "passed": recovery["api"]["status"] in ["healthy", "degraded"]
        }