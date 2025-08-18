"""HTTP client service for API communication."""

import asyncio
import aiohttp
import logging
from typing import Optional, Dict, Any, Tuple
from config.settings import BotConfig
from utils.circuit_breaker import CircuitBreaker
from models.schemas import CircuitBreakerConfig

logger = logging.getLogger(__name__)


class HttpClient:
    """HTTP client with circuit breaker protection and session management."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Circuit breakers for different operations
        cb_config = CircuitBreakerConfig(
            failure_threshold=config.circuit_breaker_failure_threshold,
            recovery_timeout=config.circuit_breaker_recovery_timeout,
            half_open_max_calls=config.circuit_breaker_half_open_max_calls
        )
        
        self.registration_breaker = CircuitBreaker(cb_config)
        self.heartbeat_breaker = CircuitBreaker(cb_config)
        self.job_breaker = CircuitBreaker(cb_config)
        self.health_breaker = CircuitBreaker(cb_config)
    
    async def initialize(self):
        """Initialize HTTP session with retries."""
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
                logger.debug(f"Session details: connector={type(self.session.connector).__name__}, "
                           f"timeout={self.session.timeout}, closed={self.session.closed}")
                return
            except Exception as e:
                logger.warning(f"Failed to initialize session (attempt {attempt + 1}): {type(e).__name__}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
    
    async def check_connection_health(self) -> Dict[str, Any]:
        """Check and log detailed connection health information."""
        health_info = {
            "session_exists": self.session is not None,
            "session_closed": self.session.closed if self.session else True,
            "connector_type": type(self.session.connector).__name__ if self.session and self.session.connector else "None",
            "timeout": str(self.session.timeout) if self.session else "None"
        }
        
        if self.session and self.session.connector:
            connector = self.session.connector
            health_info.update({
                "total_connections": connector.limit,
                "per_host_connections": connector.limit_per_host,
                "keepalive_timeout": connector.keepalive_timeout,
                "enable_cleanup_closed": connector.enable_cleanup_closed
            })
        
        logger.info(f"Connection health check: {health_info}")
        return health_info
    
    async def close(self):
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP session closed")
    
    async def register_bot(self) -> bool:
        """Register bot with main server."""
        if not self.registration_breaker.can_execute():
            logger.warning("Registration circuit breaker is open")
            return False
        
        try:
            async with self.session.post(
                f"{self.config.main_server_url}/bots/register",
                json={"bot_id": self.config.bot_id}
            ) as response:
                if response.status == 200:
                    logger.info(f"Bot {self.config.bot_id} registered successfully")
                    self.registration_breaker.record_success()
                    return True
                else:
                    error_data = await response.json()
                    raise Exception(f"Registration failed: {error_data.get('detail', 'Unknown error')}")
                    
        except Exception as e:
            logger.error(f"Registration attempt failed: {e}")
            self.registration_breaker.record_failure()
            return False
    
    async def send_heartbeat(self) -> bool:
        """Send heartbeat to main server."""
        if not self.heartbeat_breaker.can_execute():
            logger.debug("Heartbeat circuit breaker is open")
            return False
        
        try:
            async with self.session.post(
                f"{self.config.main_server_url}/bots/heartbeat",
                json={"bot_id": self.config.bot_id}
            ) as response:
                if response.status == 200:
                    logger.debug(f"Heartbeat sent: {self.config.bot_id}")
                    self.heartbeat_breaker.record_success()
                    return True
                else:
                    error_data = await response.json()
                    logger.error(f"Heartbeat failed: {error_data.get('detail', 'Unknown error')}")
                    self.heartbeat_breaker.record_failure()
                    return False
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            self.heartbeat_breaker.record_failure()
            return False
    
    async def claim_job(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Claim a job from the main server."""
        if not self.job_breaker.can_execute():
            logger.debug("Job claim circuit breaker is open")
            return False, None
        
        try:
            # Log request details before making the call
            logger.debug(f"Attempting to claim job for bot {self.config.bot_id}")
            logger.debug(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            
            async with self.session.post(
                f"{self.config.main_server_url}/jobs/claim",
                json={"bot_id": self.config.bot_id}
            ) as response:
                if response.status == 204:
                    logger.debug(f"No jobs available for bot {self.config.bot_id}")
                    self.job_breaker.record_success()
                    return True, None
                
                if response.status == 409:
                    logger.debug("Bot already has an active job")
                    self.job_breaker.record_success()
                    return True, None
                
                if response.status == 200:
                    job_data = await response.json()
                    logger.info(f"Job claimed: {job_data['id']} ({job_data['a']} + {job_data['b']})")
                    self.job_breaker.record_success()
                    return True, job_data
                
                error_data = await response.json()
                self.job_breaker.record_failure()
                raise Exception(error_data.get("detail", "Failed to claim job"))
                
        except aiohttp.ClientError as e:
            # Specific aiohttp client errors
            logger.error(f"HTTP client error claiming job: {type(e).__name__}: {e}")
            logger.error(f"Session details: closed={self.session.closed if self.session else 'No session'}, "
                        f"connector={type(self.session.connector).__name__ if self.session and self.session.connector else 'No connector'}")
            self.job_breaker.record_failure()
            return False, None
        except aiohttp.ServerTimeoutError as e:
            # Timeout specific error
            logger.error(f"Timeout error claiming job: {e}")
            self.job_breaker.record_failure()
            return False, None
        except aiohttp.ClientOSError as e:
            # OS-level connection errors (broken pipe, connection refused, etc.)
            logger.error(f"OS connection error claiming job: {type(e).__name__}: {e}")
            logger.error(f"Error code: {e.errno}, Error message: {e.strerror}")
            self.job_breaker.record_failure()
            return False, None
        except Exception as e:
            # Generic exception with full context
            logger.error(f"Failed to claim job: {type(e).__name__}: {e}")
            logger.error(f"Full error context: {str(e)}")
            logger.error(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(f"Traceback: {''.join(traceback.format_tb(e.__traceback__))}")
            self.job_breaker.record_failure()
            return False, None
    
    async def start_job(self, job_id: str) -> bool:
        """Mark job as started."""
        try:
            # Log request details before making the call
            logger.debug(f"Attempting to start job {job_id}")
            logger.debug(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            
            async with self.session.post(
                f"{self.config.main_server_url}/jobs/{job_id}/start",
                json={"bot_id": self.config.bot_id}
            ) as response:
                if response.status == 200:
                    logger.info(f"Started processing job {job_id}")
                    return True
                else:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to start job"))
        except aiohttp.ClientError as e:
            # Specific aiohttp client errors
            logger.error(f"HTTP client error starting job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Session details: closed={self.session.closed if self.session else 'No session'}, "
                        f"connector={type(self.session.connector).__name__ if self.session and self.session.connector else 'No connector'}")
            return False
        except aiohttp.ServerTimeoutError as e:
            # Timeout specific error
            logger.error(f"Timeout error starting job {job_id}: {e}")
            return False
        except aiohttp.ClientOSError as e:
            # OS-level connection errors (broken pipe, connection refused, etc.)
            logger.error(f"OS connection error starting job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Error code: {e.errno}, Error message: {e.strerror}")
            return False
        except Exception as e:
            # Generic exception with full context
            logger.error(f"Failed to start job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Full error context: {str(e)}")
            logger.error(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(f"Traceback: {''.join(traceback.format_tb(e.__traceback__))}")
            return False
    
    async def complete_job(self, job_id: str, result: int, duration_ms: int) -> bool:
        """Mark job as completed successfully."""
        try:
            # Log request details before making the call
            logger.debug(f"Attempting to complete job {job_id} with result {result} ({duration_ms}ms)")
            logger.debug(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            
            async with self.session.post(
                f"{self.config.main_server_url}/jobs/{job_id}/complete",
                json={
                    "bot_id": self.config.bot_id,
                    "result": result,
                    "duration_ms": duration_ms
                }
            ) as response:
                if response.status == 200:
                    logger.info(f"Job completed successfully: {job_id} = {result} ({duration_ms}ms)")
                    return True
                else:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to complete job"))
        except aiohttp.ClientError as e:
            # Specific aiohttp client errors
            logger.error(f"HTTP client error completing job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Session details: closed={self.session.closed if self.session else 'No session'}, "
                        f"connector={type(self.session.connector).__name__ if self.session and self.session.connector else 'No connector'}")
            return False
        except aiohttp.ServerTimeoutError as e:
            # Timeout specific error
            logger.error(f"Timeout error completing job {job_id}: {e}")
            return False
        except aiohttp.ClientOSError as e:
            # OS-level connection errors (broken pipe, connection refused, etc.)
            logger.error(f"OS connection error completing job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Error code: {e.errno}, Error message: {e.strerror}")
            return False
        except Exception as e:
            # Generic exception with full context
            logger.error(f"Failed to complete job {job_id}: {type(e).__name__}: {e}")
            logger.error(f"Full error context: {str(e)}")
            logger.error(f"Session state: closed={self.session.closed if self.session else 'No session'}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(f"Traceback: {''.join(traceback.format_tb(e.__traceback__))}")
            return False
    
    async def fail_job(self, job_id: str, error_message: str) -> bool:
        """Mark job as failed."""
        try:
            async with self.session.post(
                f"{self.config.main_server_url}/jobs/{job_id}/fail",
                json={
                    "bot_id": self.config.bot_id,
                    "error": error_message
                }
            ) as response:
                if response.status == 200:
                    logger.info(f"Job failed: {job_id} - {error_message}")
                    return True
                else:
                    error_data = await response.json()
                    raise Exception(error_data.get("detail", "Failed to fail job"))
        except Exception as e:
            logger.error(f"Failed to fail job {job_id}: {e}")
            return False
    
    async def get_health_status(self, endpoint: str) -> bool:
        """Check health status of an endpoint."""
        if not self.health_breaker.can_execute():
            return False
        
        try:
            async with self.session.get(f"{self.config.main_server_url}{endpoint}") as response:
                success = response.status == 200
                if success:
                    self.health_breaker.record_success()
                else:
                    self.health_breaker.record_failure()
                return success
        except Exception as e:
            logger.error(f"Health check failed for {endpoint}: {e}")
            self.health_breaker.record_failure()
            return False
    
    async def get_bots_list(self) -> Optional[list]:
        """Get list of registered bots."""
        try:
            async with self.session.get(f"{self.config.main_server_url}/bots") as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.error(f"Failed to get bots list: {e}")
            return None
    
    async def get_metrics(self) -> Optional[dict]:
        """Get server metrics."""
        try:
            async with self.session.get(f"{self.config.main_server_url}/metrics") as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            return None
    
    def get_circuit_breaker_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            "registration": self.registration_breaker.get_state_info(),
            "heartbeat": self.heartbeat_breaker.get_state_info(),
            "job_claim": self.job_breaker.get_state_info(),
            "health": self.health_breaker.get_state_info()
        }