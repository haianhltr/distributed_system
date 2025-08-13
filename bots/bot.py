import asyncio
import aiohttp
import os
import signal
import uuid
import random
import time
import logging
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BotState(Enum):
    """Bot lifecycle states"""
    INITIALIZING = "initializing"
    REGISTERING = "registering"
    HEALTH_CHECK = "health_check"
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

@dataclass
class RetryConfig:
    """Retry configuration"""
    max_attempts: int = 10
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0

class CircuitBreaker:
    """Circuit breaker for handling repeated failures"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half_open
        self.half_open_calls = 0
    
    def can_execute(self) -> bool:
        """Check if operation can be executed"""
        if self.state == "closed":
            return True
        elif self.state == "open":
            if time.time() - self.last_failure_time > self.config.recovery_timeout:
                self.state = "half_open"
                self.half_open_calls = 0
                logger.info("Circuit breaker entering half-open state")
                return True
            return False
        else:  # half_open
            return self.half_open_calls < self.config.half_open_max_calls
    
    def record_success(self):
        """Record successful operation"""
        if self.state == "half_open":
            self.state = "closed"
            self.failure_count = 0
            logger.info("Circuit breaker reset to closed state")
        elif self.state == "closed":
            self.failure_count = 0
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == "half_open":
            self.state = "open"
            logger.warning("Circuit breaker failed in half-open state, returning to open")
        elif self.state == "closed" and self.failure_count >= self.config.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
        
        if self.state == "half_open":
            self.half_open_calls += 1

class Bot:
    def __init__(self):
        self.id = os.environ.get("BOT_ID", f"bot-{uuid.uuid4()}")
        self.main_server_url = os.environ.get("MAIN_SERVER_URL", "http://localhost:3001")
        self.heartbeat_interval = int(os.environ.get("HEARTBEAT_INTERVAL_MS", 30000)) / 1000  # Convert to seconds
        self.processing_duration = int(os.environ.get("PROCESSING_DURATION_MS", 5 * 60 * 1000)) / 1000  # Convert to seconds
        self.failure_rate = float(os.environ.get("FAILURE_RATE", 0.15))  # 15% failure rate
        
        # State management
        self.state = BotState.INITIALIZING
        self.state_changed_at = time.time()
        self.startup_attempts = 0
        self.max_startup_attempts = int(os.environ.get("MAX_STARTUP_ATTEMPTS", "20"))
        
        # Configuration
        self.retry_config = RetryConfig()
        self.circuit_breaker_config = CircuitBreakerConfig()
        
        # Circuit breakers for different operations
        self.registration_breaker = CircuitBreaker(self.circuit_breaker_config)
        self.heartbeat_breaker = CircuitBreaker(self.circuit_breaker_config)
        self.job_claim_breaker = CircuitBreaker(self.circuit_breaker_config)
        
        # Runtime state
        self.current_job: Optional[Dict[str, Any]] = None
        self.is_running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.state_monitor_task: Optional[asyncio.Task] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Metrics
        self.startup_time: Optional[float] = None
        self.registration_attempts = 0
        self.health_check_failures = 0
        self.total_jobs_processed = 0
        
        logger.info(f"Bot initialized: {self.id}")
        logger.info(f"Main server: {self.main_server_url}")
        logger.info(f"Processing duration: {self.processing_duration}s")
        logger.info(f"Failure rate: {self.failure_rate * 100}%")
        logger.info(f"Max startup attempts: {self.max_startup_attempts}")
    
    async def start(self):
        """Start the bot with robust state machine"""
        startup_start = time.time()
        self.is_running = True
        
        try:
            # Create HTTP session with retries
            await self._initialize_session()
            
            # Start state monitor
            self.state_monitor_task = asyncio.create_task(self._state_monitor())
            
            # Run state machine until ready or max attempts exceeded
            await self._run_startup_sequence()
            
            if self.state == BotState.READY:
                self.startup_time = time.time() - startup_start
                logger.info(f"Bot {self.id} started successfully in {self.startup_time:.2f}s after {self.startup_attempts} attempts")
                
                # Start heartbeat
                self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
                
                # Start job processing
                await self.job_loop()
            else:
                raise Exception(f"Bot failed to reach READY state after {self.max_startup_attempts} attempts")
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            await self.stop()
            raise
    
    def _change_state(self, new_state: BotState):
        """Change bot state with logging"""
        old_state = self.state
        self.state = new_state
        self.state_changed_at = time.time()
        logger.info(f"Bot {self.id} state changed: {old_state.value} -> {new_state.value}")
    
    async def _initialize_session(self):
        """Initialize HTTP session with retries"""
        for attempt in range(3):
            try:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30),
                    connector=aiohttp.TCPConnector(
                        limit=10,
                        limit_per_host=5,
                        keepalive_timeout=30,
                        enable_cleanup_closed=True
                    )
                )
                logger.info(f"HTTP session initialized on attempt {attempt + 1}")
                return
            except Exception as e:
                logger.warning(f"Failed to initialize session (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
    
    async def _run_startup_sequence(self):
        """Run the startup state machine"""
        while self.startup_attempts < self.max_startup_attempts and self.is_running:
            self.startup_attempts += 1
            
            try:
                if self.state == BotState.INITIALIZING:
                    self._change_state(BotState.REGISTERING)
                
                elif self.state == BotState.REGISTERING:
                    if await self._attempt_registration():
                        self._change_state(BotState.HEALTH_CHECK)
                    else:
                        await self._handle_registration_failure()
                
                elif self.state == BotState.HEALTH_CHECK:
                    if await self._perform_health_checks():
                        self._change_state(BotState.READY)
                        return  # Success!
                    else:
                        await self._handle_health_check_failure()
                
                elif self.state == BotState.ERROR:
                    await self._handle_error_recovery()
                
                elif self.state == BotState.READY:
                    return  # Success!
                
            except Exception as e:
                logger.error(f"Startup sequence error in state {self.state.value}: {e}")
                self._change_state(BotState.ERROR)
                await asyncio.sleep(min(2 ** min(self.startup_attempts, 6), 60))  # Exponential backoff
    
    async def _attempt_registration(self) -> bool:
        """Attempt to register with circuit breaker"""
        if not self.registration_breaker.can_execute():
            logger.warning("Registration circuit breaker is open")
            return False
        
        try:
            self.registration_attempts += 1
            logger.info(f"Attempting registration (attempt {self.registration_attempts})")
            
            async with self.session.post(
                f"{self.main_server_url}/bots/register",
                json={"bot_id": self.id}
            ) as response:
                if response.status == 200:
                    logger.info(f"Bot {self.id} registered successfully")
                    self.registration_breaker.record_success()
                    return True
                else:
                    error_data = await response.json()
                    raise Exception(f"Registration failed: {error_data.get('detail', 'Unknown error')}")
                    
        except Exception as e:
            logger.error(f"Registration attempt failed: {e}")
            self.registration_breaker.record_failure()
            return False
    
    async def _perform_health_checks(self) -> bool:
        """Perform comprehensive health checks"""
        checks = [
            ("Registration Verification", self._verify_registration),
            ("Server Connectivity", self._check_server_connectivity),
            ("Database Health", self._check_database_health)
        ]
        
        for check_name, check_func in checks:
            try:
                logger.debug(f"Performing health check: {check_name}")
                if not await check_func():
                    logger.warning(f"Health check failed: {check_name}")
                    return False
                logger.debug(f"Health check passed: {check_name}")
            except Exception as e:
                logger.error(f"Health check error ({check_name}): {e}")
                return False
        
        logger.info("All health checks passed")
        return True
    
    async def _verify_registration(self) -> bool:
        """Verify bot is properly registered"""
        try:
            async with self.session.get(f"{self.main_server_url}/bots") as response:
                if response.status == 200:
                    bots = await response.json()
                    for bot in bots:
                        if bot.get('id') == self.id and not bot.get('deleted_at'):
                            return True
                    logger.warning(f"Bot {self.id} not found in registered bots")
                    return False
                else:
                    logger.warning(f"Failed to verify registration: HTTP {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Registration verification failed: {e}")
            return False
    
    async def _check_server_connectivity(self) -> bool:
        """Check main server connectivity"""
        try:
            async with self.session.get(f"{self.main_server_url}/healthz") as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Server connectivity check failed: {e}")
            return False
    
    async def _check_database_health(self) -> bool:
        """Check database health via metrics endpoint"""
        try:
            async with self.session.get(f"{self.main_server_url}/metrics") as response:
                if response.status == 200:
                    metrics = await response.json()
                    # Check if metrics contain expected data structure
                    return 'bots' in metrics and 'jobs' in metrics
                return False
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    async def _handle_registration_failure(self):
        """Handle registration failure"""
        delay = min(self.retry_config.base_delay * (self.retry_config.exponential_base ** (self.registration_attempts - 1)), 
                   self.retry_config.max_delay)
        logger.warning(f"Registration failed, retrying in {delay:.1f}s")
        await asyncio.sleep(delay)
    
    async def _handle_health_check_failure(self):
        """Handle health check failure"""
        self.health_check_failures += 1
        if self.health_check_failures >= 3:
            logger.error("Multiple health check failures, resetting to registration")
            self._change_state(BotState.REGISTERING)
            self.health_check_failures = 0
        else:
            delay = 5.0 * self.health_check_failures
            logger.warning(f"Health check failed, retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
    
    async def _handle_error_recovery(self):
        """Handle error state recovery"""
        delay = min(2.0 * self.startup_attempts, 10.0)  # Shorter delays for testing
        logger.info(f"Attempting error recovery in {delay:.1f}s")
        await asyncio.sleep(delay)
        if self.startup_attempts < self.max_startup_attempts:
            self._change_state(BotState.REGISTERING)
        else:
            logger.error("Max startup attempts reached during error recovery")
            self.is_running = False
    
    async def _state_monitor(self):
        """Monitor bot state and handle timeouts"""
        while self.is_running:
            try:
                current_time = time.time()
                time_in_state = current_time - self.state_changed_at
                
                # State timeout handling
                if self.state == BotState.REGISTERING and time_in_state > 300:  # 5 minutes
                    logger.warning("Registration taking too long, moving to error state")
                    self._change_state(BotState.ERROR)
                
                elif self.state == BotState.HEALTH_CHECK and time_in_state > 180:  # 3 minutes
                    logger.warning("Health check taking too long, moving to error state")
                    self._change_state(BotState.ERROR)
                
                # Log state metrics
                if time_in_state > 60 and int(time_in_state) % 60 == 0:  # Every minute after first minute
                    logger.info(f"Bot {self.id} has been in state {self.state.value} for {time_in_state:.0f}s")
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"State monitor error: {e}")
                await asyncio.sleep(10)
    
    async def stop(self):
        """Stop the bot gracefully"""
        logger.info(f"Stopping bot {self.id}...")
        self._change_state(BotState.SHUTTING_DOWN)
        self.is_running = False
        
        # Cancel tasks
        tasks_to_cancel = [
            self.heartbeat_task,
            self.state_monitor_task
        ]
        
        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # If currently processing a job, mark it as failed
        if self.current_job:
            try:
                await self.fail_job("Bot terminated")
            except Exception as e:
                logger.error(f"Failed to mark job as failed during shutdown: {e}")
        
        # Close HTTP session
        if self.session and not self.session.closed:
            await self.session.close()
        
        self._change_state(BotState.STOPPED)
        logger.info(f"Bot {self.id} stopped successfully")
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats to main server with circuit breaker"""
        consecutive_failures = 0
        
        while self.is_running and self.state in [BotState.READY, BotState.PROCESSING]:
            try:
                if self.heartbeat_breaker.can_execute():
                    async with self.session.post(
                        f"{self.main_server_url}/bots/heartbeat",
                        json={"bot_id": self.id}
                    ) as response:
                        if response.status == 200:
                            logger.debug(f"Heartbeat sent: {self.id}")
                            self.heartbeat_breaker.record_success()
                            consecutive_failures = 0
                        else:
                            error_data = await response.json()
                            logger.error(f"Heartbeat failed: {error_data.get('detail', 'Unknown error')}")
                            self.heartbeat_breaker.record_failure()
                            consecutive_failures += 1
                else:
                    logger.warning("Heartbeat circuit breaker is open, skipping heartbeat")
                    consecutive_failures += 1
                
                # If too many consecutive failures, trigger health check
                if consecutive_failures >= 5:
                    logger.error("Too many heartbeat failures, triggering health check")
                    if not await self._perform_health_checks():
                        logger.error("Health check failed after heartbeat failures, entering error state")
                        self._change_state(BotState.ERROR)
                        break
                    consecutive_failures = 0
                
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                consecutive_failures += 1
                await asyncio.sleep(self.heartbeat_interval)
    
    async def job_loop(self):
        """Main job processing loop with state awareness"""
        while self.is_running:
            try:
                # Only process jobs when in READY state
                if self.state != BotState.READY:
                    await asyncio.sleep(5)
                    continue
                
                if not self.current_job:
                    await self.claim_job()
                
                # Wait before checking for jobs again
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Job loop error: {e}")
                # On job loop error, perform health check
                if not await self._perform_health_checks():
                    logger.error("Health check failed after job loop error")
                    self._change_state(BotState.ERROR)
                await asyncio.sleep(10)  # Wait longer on error
    
    async def claim_job(self):
        """Claim a job from the main server with circuit breaker"""
        if not self.job_claim_breaker.can_execute():
            logger.debug("Job claim circuit breaker is open")
            return
        
        try:
            async with self.session.post(
                f"{self.main_server_url}/jobs/claim",
                json={"bot_id": self.id}
            ) as response:
                if response.status == 204:
                    logger.debug(f"No jobs available for bot {self.id}")
                    self.job_claim_breaker.record_success()
                    return
                
                if response.status == 409:
                    logger.debug("Bot already has an active job")
                    self.job_claim_breaker.record_success()
                    return
                
                if response.status != 200:
                    error_data = await response.json()
                    self.job_claim_breaker.record_failure()
                    raise Exception(error_data.get("detail", "Failed to claim job"))
                
                self.current_job = await response.json()
                logger.info(f"Job claimed: {self.current_job['id']} ({self.current_job['a']} + {self.current_job['b']})")
                self.job_claim_breaker.record_success()
                
                # Change state to processing and start job
                self._change_state(BotState.PROCESSING)
                await self.start_processing()
                
        except Exception as e:
            logger.error(f"Failed to claim job: {e}")
            self.job_claim_breaker.record_failure()
    
    async def start_processing(self):
        """Start processing the current job"""
        if not self.current_job:
            return
        
        job_id = self.current_job['id']
        
        try:
            # Mark job as started
            async with self.session.post(
                f"{self.main_server_url}/jobs/{job_id}/start",
                json={"bot_id": self.id}
            ) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to start job"))
            
            logger.info(f"Started processing job {job_id}")
            
            # Simulate processing time
            start_time = time.time()
            await asyncio.sleep(self.processing_duration)
            
            await self.complete_processing(start_time)
            
        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for job {job_id}")
            if self.current_job:
                try:
                    await self.fail_job("Processing cancelled")
                except Exception as e:
                    logger.error(f"Failed to mark job as failed during cancellation: {e}")
        except Exception as e:
            logger.error(f"Failed to start processing job {job_id}: {e}")
            if self.current_job:
                try:
                    await self.fail_job(f"Processing error: {str(e)}")
                except Exception as fe:
                    logger.error(f"Failed to mark job as failed: {fe}")
        finally:
            # Always clean up and return to ready state
            self.current_job = None
            if self.state == BotState.PROCESSING:
                self._change_state(BotState.READY)
            self.total_jobs_processed += 1
    
    async def complete_processing(self, start_time: float):
        """Complete processing of the current job"""
        if not self.current_job:
            return
        
        duration_ms = int((time.time() - start_time) * 1000)
        should_fail = random.random() < self.failure_rate
        
        try:
            if should_fail:
                await self.fail_job("Random processing failure")
            else:
                sum_result = self.current_job['a'] + self.current_job['b']
                await self.complete_job(sum_result, duration_ms)
        except Exception as e:
            logger.error(f"Failed to complete processing: {e}")
            # Try to fail the job if completion failed
            try:
                await self.fail_job(f"Completion error: {str(e)}")
            except Exception as fe:
                logger.error(f"Failed to mark job as failed after completion error: {fe}")
    
    async def complete_job(self, sum_result: int, duration_ms: int):
        """Mark job as completed successfully"""
        if not self.current_job:
            return
        
        try:
            async with self.session.post(
                f"{self.main_server_url}/jobs/{self.current_job['id']}/complete",
                json={
                    "bot_id": self.id,
                    "sum": sum_result,
                    "duration_ms": duration_ms
                }
            ) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to complete job"))
            
            logger.info(f"Job completed successfully: {self.current_job['id']} = {sum_result} ({duration_ms}ms)")
            
        except Exception as e:
            raise Exception(f"Complete job failed: {e}")
    
    async def fail_job(self, error_message: str):
        """Mark job as failed"""
        if not self.current_job:
            return
        
        try:
            async with self.session.post(
                f"{self.main_server_url}/jobs/{self.current_job['id']}/fail",
                json={
                    "bot_id": self.id,
                    "error": error_message
                }
            ) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to fail job"))
            
            logger.info(f"Job failed: {self.current_job['id']} - {error_message}")
            
        except Exception as e:
            raise Exception(f"Fail job failed: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get bot metrics for observability"""
        uptime = time.time() - (self.startup_time or time.time()) if self.startup_time else 0
        
        return {
            "bot_id": self.id,
            "state": self.state.value,
            "uptime_seconds": uptime,
            "startup_time_seconds": self.startup_time,
            "startup_attempts": self.startup_attempts,
            "registration_attempts": self.registration_attempts,
            "health_check_failures": self.health_check_failures,
            "total_jobs_processed": self.total_jobs_processed,
            "circuit_breakers": {
                "registration": {
                    "state": self.registration_breaker.state,
                    "failure_count": self.registration_breaker.failure_count
                },
                "heartbeat": {
                    "state": self.heartbeat_breaker.state,
                    "failure_count": self.heartbeat_breaker.failure_count
                },
                "job_claim": {
                    "state": self.job_claim_breaker.state,
                    "failure_count": self.job_claim_breaker.failure_count
                }
            },
            "current_job": self.current_job['id'] if self.current_job else None,
            "time_in_current_state": time.time() - self.state_changed_at
        }
    
    def log_metrics(self):
        """Log current metrics"""
        metrics = self.get_metrics()
        logger.info(f"Bot metrics: {json.dumps(metrics, indent=2)}")

# Global bot instance for signal handling
bot_instance: Optional[Bot] = None

async def shutdown_handler():
    """Handle graceful shutdown"""
    if bot_instance:
        await bot_instance.stop()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    asyncio.create_task(shutdown_handler())

async def main():
    """Main entry point"""
    global bot_instance
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    bot_instance = Bot()
    
    try:
        await bot_instance.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
    finally:
        if bot_instance:
            await bot_instance.stop()

if __name__ == "__main__":
    asyncio.run(main())