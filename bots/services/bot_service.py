"""Main bot service with state management and job processing."""

import asyncio
import time
import random
import logging
from typing import Optional, Dict, Any
from models.enums import BotState
from models.schemas import JobData, BotMetrics
from config.settings import BotConfig
from services.http_client import HttpClient
from services.health_service import HealthService
from services.operation_service import OperationService
from utils.retry import RetryHandler
from models.schemas import RetryConfig

logger = logging.getLogger(__name__)


class BotService:
    """Main bot service orchestrating all bot operations."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        
        # State management
        self.state = BotState.INITIALIZING
        self.state_changed_at = time.time()
        self.startup_attempts = 0
        self.is_running = False
        
        # Services
        self.http_client = HttpClient(config)
        self.health_service = HealthService(config, self.http_client)
        self.operation_service = OperationService()
        self.retry_handler = RetryHandler(RetryConfig(
            max_attempts=config.retry_max_attempts,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
            exponential_base=config.retry_exponential_base
        ))
        
        # Background tasks
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.state_monitor_task: Optional[asyncio.Task] = None
        
        # Job processing
        self.current_job: Optional[JobData] = None
        
        # Metrics
        self.startup_time: Optional[float] = None
        self.registration_attempts = 0
        self.health_check_failures = 0
        self.total_jobs_processed = 0
        
        logger.info(f"Bot service initialized: {self.config.bot_id}")
        logger.info(f"Main server: {self.config.main_server_url}")
        logger.info(f"Processing duration: {self.config.processing_duration}s")
        logger.info(f"Failure rate: {self.config.failure_rate * 100}%")
    
    async def start(self):
        """Start the bot with robust state machine."""
        startup_start = time.time()
        self.is_running = True
        
        try:
            # Initialize HTTP client
            await self.http_client.initialize()
            
            # Load operation plugins
            self.operation_service.load_operations()
            
            # Start state monitor
            self.state_monitor_task = asyncio.create_task(self._state_monitor())
            
            # Run startup sequence
            await self._run_startup_sequence()
            
            if self.state == BotState.READY:
                self.startup_time = time.time() - startup_start
                logger.info(f"Bot {self.config.bot_id} started successfully in {self.startup_time:.2f}s after {self.startup_attempts} attempts")
                
                # Start heartbeat
                self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                # Start job processing
                await self._job_loop()
            else:
                raise Exception(f"Bot failed to reach READY state after {self.config.max_startup_attempts} attempts")
                
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the bot gracefully."""
        logger.info(f"Stopping bot {self.config.bot_id}...")
        self._change_state(BotState.SHUTTING_DOWN)
        self.is_running = False
        
        # Cancel background tasks
        tasks_to_cancel = [self.heartbeat_task, self.state_monitor_task]
        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Handle current job
        if self.current_job:
            try:
                await self.http_client.fail_job(self.current_job.id, "Bot terminated")
            except Exception as e:
                logger.error(f"Failed to mark job as failed during shutdown: {e}")
        
        # Close HTTP client
        await self.http_client.close()
        
        self._change_state(BotState.STOPPED)
        logger.info(f"Bot {self.config.bot_id} stopped successfully")
    
    def _change_state(self, new_state: BotState):
        """Change bot state with logging."""
        old_state = self.state
        self.state = new_state
        self.state_changed_at = time.time()
        logger.info(f"Bot {self.config.bot_id} state changed: {old_state.value} -> {new_state.value}")
    
    async def _run_startup_sequence(self):
        """Run the startup state machine."""
        while self.startup_attempts < self.config.max_startup_attempts and self.is_running:
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
                    if await self.health_service.perform_all_checks():
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
                await asyncio.sleep(min(2 ** min(self.startup_attempts, 6), 60))
    
    async def _attempt_registration(self) -> bool:
        """Attempt to register with the main server."""
        self.registration_attempts += 1
        logger.info(f"Attempting registration (attempt {self.registration_attempts})")
        
        return await self.http_client.register_bot()
    
    async def _handle_registration_failure(self):
        """Handle registration failure with exponential backoff."""
        delay = self.retry_handler.calculate_delay(self.registration_attempts)
        logger.warning(f"Registration failed, retrying in {delay:.1f}s")
        await asyncio.sleep(delay)
    
    async def _handle_health_check_failure(self):
        """Handle health check failure."""
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
        """Handle error state recovery."""
        delay = min(2.0 * self.startup_attempts, 10.0)
        logger.info(f"Attempting error recovery in {delay:.1f}s")
        await asyncio.sleep(delay)
        if self.startup_attempts < self.config.max_startup_attempts:
            self._change_state(BotState.REGISTERING)
        else:
            logger.error("Max startup attempts reached during error recovery")
            self.is_running = False
    
    async def _state_monitor(self):
        """Monitor bot state and handle timeouts."""
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
                
                # Log state metrics periodically
                if time_in_state > 60 and int(time_in_state) % 60 == 0:
                    logger.info(f"Bot {self.config.bot_id} has been in state {self.state.value} for {time_in_state:.0f}s")
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"State monitor error: {e}")
                await asyncio.sleep(10)
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to main server."""
        consecutive_failures = 0
        
        while self.is_running and self.state in [BotState.READY, BotState.PROCESSING]:
            try:
                success = await self.http_client.send_heartbeat()
                
                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                
                # If too many consecutive failures, trigger health check
                if consecutive_failures >= 5:
                    logger.error("Too many heartbeat failures, triggering health check")
                    if not await self.health_service.perform_all_checks():
                        logger.error("Health check failed after heartbeat failures, entering error state")
                        self._change_state(BotState.ERROR)
                        break
                    consecutive_failures = 0
                
                await asyncio.sleep(self.config.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                consecutive_failures += 1
                await asyncio.sleep(self.config.heartbeat_interval)
    
    async def _job_loop(self):
        """Main job processing loop."""
        while self.is_running:
            try:
                # Only process jobs when in READY state
                if self.state != BotState.READY:
                    await asyncio.sleep(5)
                    continue
                
                if not self.current_job:
                    await self._claim_job()
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Job loop error: {e}")
                # On job loop error, perform health check
                if not await self.health_service.perform_all_checks():
                    logger.error("Health check failed after job loop error")
                    self._change_state(BotState.ERROR)
                await asyncio.sleep(10)
    
    async def _claim_job(self):
        """Claim a job from the main server."""
        success, job_data = await self.http_client.claim_job()
        
        if success and job_data:
            self.current_job = JobData(
                id=job_data['id'],
                a=job_data['a'],
                b=job_data['b'],
                operation=job_data.get('operation', 'sum'),
                status=job_data.get('status')
            )
            
            # Change state to processing and start job
            self._change_state(BotState.PROCESSING)
            await self._process_job()
    
    async def _process_job(self):
        """Process the current job."""
        if not self.current_job:
            return
        
        job_id = self.current_job.id
        
        try:
            # Mark job as started
            if not await self.http_client.start_job(job_id):
                raise Exception("Failed to start job")
            
            # Simulate processing time
            start_time = time.time()
            await asyncio.sleep(self.config.processing_duration)
            
            # Complete processing
            await self._complete_processing(start_time)
            
        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for job {job_id}")
            if self.current_job:
                await self.http_client.fail_job(job_id, "Processing cancelled")
        except Exception as e:
            logger.error(f"Failed to process job {job_id}: {e}")
            if self.current_job:
                await self.http_client.fail_job(job_id, f"Processing error: {str(e)}")
        finally:
            # Always clean up and return to ready state
            self.current_job = None
            if self.state == BotState.PROCESSING:
                self._change_state(BotState.READY)
            self.total_jobs_processed += 1
    
    async def _complete_processing(self, start_time: float):
        """Complete processing of the current job."""
        if not self.current_job:
            return
        
        duration_ms = int((time.time() - start_time) * 1000)
        should_fail = random.random() < self.config.failure_rate
        
        if should_fail:
            await self.http_client.fail_job(self.current_job.id, "Random processing failure")
        else:
            try:
                # Execute the operation using the plugin system
                result = self.operation_service.execute_operation(
                    self.current_job.operation,
                    self.current_job.a,
                    self.current_job.b
                )
                await self.http_client.complete_job(self.current_job.id, result, duration_ms)
                logger.info(f"Job {self.current_job.id} completed: {self.current_job.a} {self.current_job.operation} {self.current_job.b} = {result}")
            except Exception as e:
                # Operation execution failed
                error_msg = f"Operation '{self.current_job.operation}' failed: {str(e)}"
                logger.error(error_msg)
                await self.http_client.fail_job(self.current_job.id, error_msg)
    
    def get_metrics(self) -> BotMetrics:
        """Get bot metrics for observability."""
        uptime = time.time() - (self.startup_time or time.time()) if self.startup_time else 0
        
        return BotMetrics(
            bot_id=self.config.bot_id,
            state=self.state.value,
            uptime_seconds=uptime,
            startup_time_seconds=self.startup_time,
            startup_attempts=self.startup_attempts,
            registration_attempts=self.registration_attempts,
            health_check_failures=self.health_check_failures,
            total_jobs_processed=self.total_jobs_processed,
            circuit_breakers=self.http_client.get_circuit_breaker_status(),
            current_job=self.current_job.id if self.current_job else None,
            time_in_current_state=time.time() - self.state_changed_at
        )
    
    def log_metrics(self):
        """Log current metrics."""
        metrics = self.get_metrics()
        logger.info(f"Bot metrics: {metrics}")