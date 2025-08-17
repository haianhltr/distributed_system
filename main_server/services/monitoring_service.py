"""Consolidated monitoring service for job state recovery."""

import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod
import structlog

from database import DatabaseManager

# Simplified service dependencies - we'll work directly with the database
class BotService:
    def __init__(self, db_manager):
        self.db = db_manager

class JobService:
    def __init__(self, db_manager, datalake_manager):
        self.db = db_manager
        self.datalake = datalake_manager

logger = structlog.get_logger(__name__)


@dataclass
class MonitoringConfig:
    """Configuration for the job monitoring system."""
    
    # Core monitoring settings
    monitoring_enabled: bool = True
    check_interval_seconds: int = 60
    
    # Claimed job monitoring
    claimed_job_monitoring_enabled: bool = True
    claimed_job_timeout_seconds: int = 300  # 5 minutes
    
    # Processing job monitoring  
    processing_job_monitoring_enabled: bool = True
    processing_job_timeout_seconds: int = 600  # 10 minutes
    
    # Advanced settings
    max_recovery_attempts_per_cycle: int = 100
    recovery_batch_size: int = 10
    enable_metrics: bool = True
    enable_detailed_logging: bool = True
    
    @classmethod
    def from_env(cls) -> 'MonitoringConfig':
        """Create configuration from environment variables."""
        config = cls()
        
        # Core settings
        config.monitoring_enabled = os.environ.get(
            'JOB_MONITORING_ENABLED', 'true'
        ).lower() == 'true'
        
        config.check_interval_seconds = int(os.environ.get(
            'JOB_MONITORING_INTERVAL_SECONDS', '60'
        ))
        
        # Claimed job settings
        config.claimed_job_monitoring_enabled = os.environ.get(
            'CLAIMED_JOB_MONITORING_ENABLED', 'true'
        ).lower() == 'true'
        
        config.claimed_job_timeout_seconds = int(os.environ.get(
            'CLAIMED_JOB_TIMEOUT_SECONDS', '300'
        ))
        
        # Processing job settings
        config.processing_job_monitoring_enabled = os.environ.get(
            'PROCESSING_JOB_MONITORING_ENABLED', 'true'
        ).lower() == 'true'
        
        config.processing_job_timeout_seconds = int(os.environ.get(
            'PROCESSING_JOB_TIMEOUT_SECONDS', '600'
        ))
        
        # Advanced settings
        config.max_recovery_attempts_per_cycle = int(os.environ.get(
            'MAX_RECOVERY_ATTEMPTS_PER_CYCLE', '100'
        ))
        
        config.recovery_batch_size = int(os.environ.get(
            'RECOVERY_BATCH_SIZE', '10'
        ))
        
        config.enable_metrics = os.environ.get(
            'MONITORING_ENABLE_METRICS', 'true'
        ).lower() == 'true'
        
        config.enable_detailed_logging = os.environ.get(
            'MONITORING_ENABLE_DETAILED_LOGGING', 'true'
        ).lower() == 'true'
        
        return config
    
    def validate(self) -> bool:
        """Validate configuration values."""
        errors = []
        
        if self.check_interval_seconds < 10:
            errors.append("check_interval_seconds must be at least 10 seconds")
        
        if self.claimed_job_timeout_seconds < 60:
            errors.append("claimed_job_timeout_seconds must be at least 60 seconds")
        
        if self.processing_job_timeout_seconds < 60:
            errors.append("processing_job_timeout_seconds must be at least 60 seconds")
        
        if self.max_recovery_attempts_per_cycle < 1:
            errors.append("max_recovery_attempts_per_cycle must be at least 1")
        
        if self.recovery_batch_size < 1:
            errors.append("recovery_batch_size must be at least 1")
        
        if errors:
            for error in errors:
                logger.error(f"Configuration validation error: {error}")
            return False
        
        return True
    
    def log_configuration(self):
        """Log the current configuration."""
        logger.info(
            "Job monitoring configuration",
            monitoring_enabled=self.monitoring_enabled,
            check_interval_seconds=self.check_interval_seconds,
            claimed_job_monitoring_enabled=self.claimed_job_monitoring_enabled,
            claimed_job_timeout_seconds=self.claimed_job_timeout_seconds,
            processing_job_monitoring_enabled=self.processing_job_monitoring_enabled,
            processing_job_timeout_seconds=self.processing_job_timeout_seconds,
            max_recovery_attempts_per_cycle=self.max_recovery_attempts_per_cycle,
            recovery_batch_size=self.recovery_batch_size,
            enable_metrics=self.enable_metrics,
            enable_detailed_logging=self.enable_detailed_logging
        )


class JobMonitor(ABC):
    """Abstract base class for job state monitors."""
    
    def __init__(self, db_manager: DatabaseManager, job_service: JobService, bot_service: BotService):
        self.db = db_manager
        self.job_service = job_service
        self.bot_service = bot_service
        self.enabled = True
        self.last_check = None
        self.recovered_count = 0
        self.error_count = 0
        
    @abstractmethod
    def get_monitor_name(self) -> str:
        """Return the name of this monitor."""
        pass
    
    @abstractmethod
    def get_job_state(self) -> str:
        """Return the job state this monitor handles."""
        pass
    
    @abstractmethod
    async def detect_stuck_jobs(self) -> List[Dict[str, Any]]:
        """Detect jobs stuck in this monitor's state."""
        pass
    
    @abstractmethod
    async def recover_job(self, job: Dict[str, Any]) -> bool:
        """Recover a single stuck job. Returns True if successful."""
        pass
    
    async def run_check_cycle(self) -> Dict[str, Any]:
        """Run a complete check and recovery cycle."""
        if not self.enabled:
            return {
                "monitor": self.get_monitor_name(),
                "status": "disabled",
                "checked": 0,
                "recovered": 0
            }
        
        start_time = datetime.utcnow()
        stuck_jobs = []
        recovered = 0
        errors = 0
        
        try:
            # Detect stuck jobs
            stuck_jobs = await self.detect_stuck_jobs()
            logger.info(
                f"{self.get_monitor_name()} detected stuck jobs",
                count=len(stuck_jobs),
                state=self.get_job_state()
            )
            
            # Recover each stuck job
            for job in stuck_jobs:
                try:
                    if await self.recover_job(job):
                        recovered += 1
                        self.recovered_count += 1
                    else:
                        errors += 1
                        self.error_count += 1
                except Exception as e:
                    logger.error(
                        f"{self.get_monitor_name()} failed to recover job",
                        job_id=job.get('id'),
                        error=str(e)
                    )
                    errors += 1
                    self.error_count += 1
            
            self.last_check = datetime.utcnow()
            
            return {
                "monitor": self.get_monitor_name(),
                "status": "success",
                "checked": len(stuck_jobs),
                "recovered": recovered,
                "errors": errors,
                "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000)
            }
            
        except Exception as e:
            logger.error(
                f"{self.get_monitor_name()} check cycle failed",
                error=str(e)
            )
            self.error_count += 1
            return {
                "monitor": self.get_monitor_name(),
                "status": "error",
                "error": str(e),
                "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000)
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics."""
        return {
            "monitor": self.get_monitor_name(),
            "state": self.get_job_state(),
            "enabled": self.enabled,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "total_recovered": self.recovered_count,
            "total_errors": self.error_count
        }


class ClaimedJobMonitor(JobMonitor):
    """Monitor for jobs stuck in 'claimed' state."""
    
    def __init__(self, db_manager: DatabaseManager, job_service: JobService, bot_service: BotService, config: MonitoringConfig):
        super().__init__(db_manager, job_service, bot_service)
        self.config = config
        self.enabled = config.claimed_job_monitoring_enabled
        self.timeout_seconds = config.claimed_job_timeout_seconds
    
    def get_monitor_name(self) -> str:
        return "ClaimedJobMonitor"
    
    def get_job_state(self) -> str:
        return "claimed"
    
    async def detect_stuck_jobs(self) -> List[Dict[str, Any]]:
        """Detect jobs stuck in claimed state."""
        try:
            async with self.db.get_connection() as conn:
                # Find jobs claimed but not started within timeout
                stuck_jobs = await conn.fetch("""
                    SELECT j.*, b.id as bot_id, b.status as bot_status,
                           EXTRACT(EPOCH FROM (NOW() - j.claimed_at)) as stuck_seconds
                    FROM jobs j
                    LEFT JOIN bots b ON j.claimed_by = b.id
                    WHERE j.status = 'claimed'
                    AND j.claimed_at < NOW() - INTERVAL '1 second' * $1
                    ORDER BY j.claimed_at ASC
                    LIMIT $2
                """, self.timeout_seconds, self.config.max_recovery_attempts_per_cycle)
                
                results = []
                for job in stuck_jobs:
                    job_dict = dict(job)
                    if self.config.enable_detailed_logging:
                        logger.warning(
                            "Detected stuck claimed job",
                            job_id=job_dict['id'],
                            claimed_by=job_dict['claimed_by'],
                            claimed_at=job_dict['claimed_at'].isoformat(),
                            stuck_seconds=int(job_dict['stuck_seconds']),
                            bot_status=job_dict.get('bot_status')
                        )
                    results.append(job_dict)
                
                return results
                
        except Exception as e:
            logger.error("Failed to detect stuck claimed jobs", error=str(e))
            raise
    
    async def recover_job(self, job: Dict[str, Any]) -> bool:
        """Recover a job stuck in claimed state."""
        job_id = job['id']
        bot_id = job.get('claimed_by')
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Reset job to pending state
                    result = await conn.execute("""
                        UPDATE jobs 
                        SET status = 'pending', 
                            claimed_by = NULL, 
                            claimed_at = NULL,
                            attempts = attempts + 1
                        WHERE id = $1 AND status = 'claimed'
                    """, job_id)
                    
                    if result == 'UPDATE 0':
                        logger.warning(
                            "Job state changed during recovery",
                            job_id=job_id,
                            expected_state='claimed'
                        )
                        return False
                    
                    # Reset bot state if it's stuck with this job
                    if bot_id:
                        await conn.execute("""
                            UPDATE bots 
                            SET current_job_id = NULL, 
                                status = 'idle'
                            WHERE id = $1 
                            AND current_job_id = $2
                        """, bot_id, job_id)
                    
                    logger.info(
                        "Recovered stuck claimed job",
                        job_id=job_id,
                        bot_id=bot_id,
                        stuck_duration_seconds=int(job.get('stuck_seconds', 0))
                    )
                    
                    return True
                    
        except Exception as e:
            logger.error(
                "Failed to recover claimed job",
                job_id=job_id,
                error=str(e)
            )
            return False


class ProcessingJobMonitor(JobMonitor):
    """Monitor for jobs stuck in 'processing' state."""
    
    def __init__(self, db_manager: DatabaseManager, job_service: JobService, bot_service: BotService, config: MonitoringConfig):
        super().__init__(db_manager, job_service, bot_service)
        self.config = config
        self.enabled = config.processing_job_monitoring_enabled
        self.timeout_seconds = config.processing_job_timeout_seconds
    
    def get_monitor_name(self) -> str:
        return "ProcessingJobMonitor"
    
    def get_job_state(self) -> str:
        return "processing"
    
    async def detect_stuck_jobs(self) -> List[Dict[str, Any]]:
        """Detect jobs stuck in processing state with active bot heartbeats (zombie bots)."""
        try:
            async with self.db.get_connection() as conn:
                # Find jobs processing longer than timeout where bot is still sending heartbeats
                stuck_jobs = await conn.fetch("""
                    SELECT j.*, b.id as bot_id, b.status as bot_status,
                           b.last_heartbeat_at,
                           EXTRACT(EPOCH FROM (NOW() - j.started_at)) as processing_seconds,
                           EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 as processing_duration_minutes,
                           EXTRACT(EPOCH FROM (NOW() - b.last_heartbeat_at)) as heartbeat_age_seconds
                    FROM jobs j
                    JOIN bots b ON j.claimed_by = b.id
                    WHERE j.status = 'processing'
                    AND j.started_at < NOW() - INTERVAL '1 second' * $1
                    AND b.last_heartbeat_at > NOW() - INTERVAL '2 minutes'
                    ORDER BY j.started_at ASC
                    LIMIT $2
                """, self.timeout_seconds, self.config.max_recovery_attempts_per_cycle)
                
                results = []
                for job in stuck_jobs:
                    job_dict = dict(job)
                    if self.config.enable_detailed_logging:
                        logger.warning(
                            "Detected stuck processing job",
                            job_id=job_dict['id'],
                            claimed_by=job_dict['claimed_by'],
                            started_at=job_dict['started_at'].isoformat(),
                            processing_seconds=int(job_dict['processing_seconds']),
                            bot_status=job_dict.get('bot_status')
                        )
                    results.append(job_dict)
                
                return results
                
        except Exception as e:
            logger.error("Failed to detect stuck processing jobs", error=str(e))
            raise
    
    async def recover_job(self, job: Dict[str, Any]) -> bool:
        """Recover a job stuck in processing state."""
        job_id = job['id']
        bot_id = job.get('claimed_by')
        
        try:
            async with self.db.get_connection() as conn:
                async with conn.transaction():
                    # Mark job as failed due to timeout
                    result = await conn.execute("""
                        UPDATE jobs 
                        SET status = 'failed', 
                            finished_at = NOW(),
                            error = 'Processing timeout exceeded',
                            attempts = attempts + 1
                        WHERE id = $1 AND status = 'processing'
                    """, job_id)
                    
                    if result == 'UPDATE 0':
                        logger.warning(
                            "Job state changed during recovery",
                            job_id=job_id,
                            expected_state='processing'
                        )
                        return False
                    
                    # Create failure result record
                    await conn.execute("""
                        INSERT INTO results (
                            id, job_id, a, b, result, operation, 
                            processed_by, processed_at, duration_ms, 
                            status, error, 
                            input_data, output_data, metadata
                        )
                        SELECT 
                            gen_random_uuid(), 
                            j.id, 
                            j.a, 
                            j.b, 
                            0, 
                            j.operation,
                            j.claimed_by, 
                            NOW(), 
                            EXTRACT(EPOCH FROM (NOW() - j.started_at)) * 1000,
                            'failed',
                            'Processing timeout exceeded',
                            jsonb_build_object('a', j.a, 'b', j.b),
                            jsonb_build_object('error', 'Processing timeout exceeded', 'result', null),
                            jsonb_build_object(
                                'operation_type', j.operation,
                                'execution_context', 'monitoring_recovery',
                                'timeout_seconds', $1::int,
                                'processing_seconds', EXTRACT(EPOCH FROM (NOW() - j.started_at))
                            )
                        FROM jobs j
                        WHERE j.id = $2
                    """, self.timeout_seconds, job_id)
                    
                    # Reset bot state if it's stuck with this job
                    if bot_id:
                        await conn.execute("""
                            UPDATE bots 
                            SET current_job_id = NULL, 
                                status = 'idle'
                            WHERE id = $1 
                            AND current_job_id = $2
                        """, bot_id, job_id)
                    
                    logger.info(
                        "Recovered stuck processing job",
                        job_id=job_id,
                        bot_id=bot_id,
                        processing_duration_seconds=int(job.get('processing_seconds', 0))
                    )
                    
                    return True
                    
        except Exception as e:
            logger.error(
                "Failed to recover processing job",
                job_id=job_id,
                error=str(e)
            )
            return False


class BotHealthMonitor(JobMonitor):
    """Monitor for bot health and potentially stuck bots."""
    
    def __init__(self, db_manager: DatabaseManager, job_service: JobService, bot_service: BotService, config: MonitoringConfig):
        super().__init__(db_manager, job_service, bot_service)
        self.config = config
        self.enabled = config.processing_job_monitoring_enabled  # Uses same config as processing monitor
        self.timeout_seconds = config.processing_job_timeout_seconds
    
    def get_monitor_name(self) -> str:
        return "BotHealthMonitor"
    
    def get_job_state(self) -> str:
        return "bot_health"
    
    async def detect_stuck_jobs(self) -> List[Dict[str, Any]]:
        """Detect bots that might be stuck processing jobs."""
        try:
            async with self.db.get_connection() as conn:
                # Mark bots as potentially stuck based on processing time
                potentially_stuck_bots = await conn.fetch("""
                    UPDATE bots b
                    SET health_status = 'potentially_stuck',
                        stuck_job_id = j.id,
                        health_checked_at = NOW()
                    FROM jobs j
                    WHERE b.id = j.claimed_by
                    AND j.status = 'processing'
                    AND j.started_at < NOW() - INTERVAL '1 second' * $1
                    AND b.last_heartbeat_at > NOW() - INTERVAL '2 minutes'
                    AND (b.health_status IS NULL OR b.health_status != 'potentially_stuck')
                    RETURNING b.id as bot_id, j.id as job_id, 
                             EXTRACT(EPOCH FROM (NOW() - j.started_at)) / 60 as processing_minutes
                """, self.timeout_seconds)
                
                # Clear health status for bots that are no longer stuck
                await conn.execute("""
                    UPDATE bots b
                    SET health_status = 'normal',
                        stuck_job_id = NULL,
                        health_checked_at = NOW()
                    WHERE b.health_status = 'potentially_stuck'
                    AND (
                        b.current_job_id IS NULL 
                        OR NOT EXISTS (
                            SELECT 1 FROM jobs j 
                            WHERE j.id = b.current_job_id 
                            AND j.status = 'processing'
                            AND j.started_at < NOW() - INTERVAL '1 second' * $1
                        )
                    )
                """, self.timeout_seconds)
                
                results = []
                for bot in potentially_stuck_bots:
                    bot_dict = dict(bot)
                    if self.config.enable_detailed_logging:
                        logger.warning(
                            "Marked bot as potentially stuck",
                            bot_id=bot_dict['bot_id'],
                            job_id=bot_dict['job_id'],
                            processing_minutes=int(bot_dict['processing_minutes'])
                        )
                    results.append(bot_dict)
                
                return results
                
        except Exception as e:
            logger.error("Failed to check bot health", error=str(e))
            raise
    
    async def recover_job(self, bot_info: Dict[str, Any]) -> bool:
        """Bot health monitor doesn't recover jobs, just marks health status."""
        # This monitor only updates health status, no recovery action
        return True


class MonitoringService:
    """Consolidated monitoring service for job state recovery."""
    
    def __init__(self, db_manager: DatabaseManager, job_service: JobService, bot_service: BotService):
        self.db_manager = db_manager
        self.job_service = job_service
        self.bot_service = bot_service
        self.config: Optional[MonitoringConfig] = None
        self.monitors: List[JobMonitor] = []
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None
        
    def initialize(self, config: Optional[MonitoringConfig] = None):
        """Initialize the monitoring service with configuration."""
        # Load configuration
        self.config = config or MonitoringConfig.from_env()
        
        # Validate configuration
        if not self.config.validate():
            raise ValueError("Invalid monitoring configuration")
        
        # Log configuration
        self.config.log_configuration()
        
        # Clear existing monitors
        self.monitors = []
        
        # Register monitors based on configuration
        if self.config.claimed_job_monitoring_enabled:
            claimed_monitor = ClaimedJobMonitor(
                self.db_manager,
                self.job_service,
                self.bot_service,
                self.config
            )
            self.monitors.append(claimed_monitor)
            logger.info("Registered ClaimedJobMonitor")
        
        if self.config.processing_job_monitoring_enabled:
            processing_monitor = ProcessingJobMonitor(
                self.db_manager,
                self.job_service,
                self.bot_service,
                self.config
            )
            self.monitors.append(processing_monitor)
            logger.info("Registered ProcessingJobMonitor")
            
            # Also register bot health monitor when processing monitor is enabled
            bot_health_monitor = BotHealthMonitor(
                self.db_manager,
                self.job_service,
                self.bot_service,
                self.config
            )
            self.monitors.append(bot_health_monitor)
            logger.info("Registered BotHealthMonitor")
        
        logger.info(
            "Monitoring service initialized",
            monitors_count=len(self.monitors),
            check_interval=self.config.check_interval_seconds
        )
    
    async def run_all_monitors(self) -> List[Dict[str, Any]]:
        """Run all registered monitors concurrently."""
        tasks = [monitor.run_check_cycle() for monitor in self.monitors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "monitor": self.monitors[i].get_monitor_name(),
                    "status": "error",
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _monitoring_loop(self):
        """Internal monitoring loop."""
        while self.running:
            try:
                results = await self.run_all_monitors()
                
                # Log summary
                total_checked = sum(r.get('checked', 0) for r in results if isinstance(r, dict))
                total_recovered = sum(r.get('recovered', 0) for r in results if isinstance(r, dict))
                total_errors = sum(r.get('errors', 0) for r in results if isinstance(r, dict))
                
                logger.info(
                    "Monitoring cycle completed",
                    total_checked=total_checked,
                    total_recovered=total_recovered,
                    total_errors=total_errors,
                    results=results
                )
                
                # Wait for next cycle
                await asyncio.sleep(self.config.check_interval_seconds)
                
            except Exception as e:
                logger.error("Monitoring cycle failed", error=str(e))
                await asyncio.sleep(self.config.check_interval_seconds)
    
    async def start(self):
        """Start the monitoring service."""
        if not self.config or not self.monitors:
            raise RuntimeError("Monitoring service not initialized")
        
        if not self.config.monitoring_enabled:
            logger.info("Job monitoring is disabled by configuration")
            return
        
        if self.monitor_task and not self.monitor_task.done():
            logger.warning("Monitoring service already running")
            return
        
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Monitoring service started")
    
    async def stop(self):
        """Stop the monitoring service."""
        logger.info("Stopping monitoring service")
        self.running = False
        
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Monitoring service stopped")
    
    async def run_manual_check(self) -> List[Dict[str, Any]]:
        """Run a manual monitoring check cycle."""
        if not self.monitors:
            raise RuntimeError("Monitoring service not initialized")
        
        logger.info("Running manual monitoring check")
        return await self.run_all_monitors()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        if not self.config:
            return {"status": "not_initialized"}
        
        return {
            "status": "running" if self.running else "stopped",
            "config": {
                "enabled": self.config.monitoring_enabled,
                "check_interval": self.config.check_interval_seconds,
                "claimed_timeout": self.config.claimed_job_timeout_seconds,
                "processing_timeout": self.config.processing_job_timeout_seconds
            },
            "monitors": [monitor.get_stats() for monitor in self.monitors]
        }