"""HTTP client service for API communication."""

import asyncio
import aiohttp
import logging
import uuid
from typing import Optional, Dict, Any, Tuple
from ..config.settings import BotConfig
from ..utils.circuit_breaker import CircuitBreaker
from ..models.schemas import CircuitBreakerConfig

logger = logging.getLogger(__name__)


class HttpClient:
    """HTTP client with circuit breaker protection and session management."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Authentication
        self.access_token: Optional[str] = None
        self.session_id: Optional[str] = None
        self.session_expires_in: Optional[int] = None
        self.heartbeat_interval: Optional[int] = None
        
        # Generate unique instance ID per process
        self.instance_id = f"i-{uuid.uuid4().hex}"
        
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
    
    async def _get_jwt_token(self) -> bool:
        """Get JWT token from /v1/auth/token endpoint."""
        try:
            auth_payload = {
                "bot_key": self.config.bot_id,  # Using bot_id as bot_key for now
                "bootstrap_secret": getattr(self.config, 'bootstrap_secret', 'default_secret')
            }
            
            async with self.session.post(
                f"{self.config.main_server_url}/v1/auth/token",
                json=auth_payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    auth_data = await response.json()
                    self.access_token = auth_data["access_token"]
                    logger.info("JWT token obtained successfully")
                    return True
                else:
                    error_data = await response.json()
                    logger.error(f"Failed to get JWT token: {error_data}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error getting JWT token: {e}")
            return False
    
    async def register_bot(self) -> bool:
        """Register bot with main server using JWT authentication and idempotency."""
        if not self.registration_breaker.can_execute():
            logger.warning("Registration circuit breaker is open")
            return False
        
        try:
            # Step 1: Get JWT token
            if not await self._get_jwt_token():
                raise Exception("Failed to obtain JWT token")
            
            # Step 2: Prepare registration request
            idempotency_key = str(uuid.uuid4())
            
            register_payload = {
                "bot_key": self.config.bot_id,
                "instance_id": self.instance_id,
                "agent": {
                    "version": "0.1.0",
                    "platform": "linux/amd64"
                },
                "capabilities": {
                    "operations": ["sum"],
                    "max_concurrency": 1
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/json"
            }
            
            # Step 3: Register with server
            async with self.session.post(
                f"{self.config.main_server_url}/v1/bots/register",
                json=register_payload,
                headers=headers
            ) as response:
                if response.status == 200:
                    registration_data = await response.json()
                    
                    # Store session information
                    session_info = registration_data.get("session", {})
                    self.session_id = session_info.get("session_id")
                    self.session_expires_in = session_info.get("expires_in_sec")
                    self.heartbeat_interval = session_info.get("heartbeat_interval_sec")
                    
                    logger.info(f"Bot {self.config.bot_id} registered successfully")
                    logger.info(f"Session ID: {self.session_id}")
                    logger.info(f"Session expires in: {self.session_expires_in}s")
                    
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