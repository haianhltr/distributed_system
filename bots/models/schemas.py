"""Data classes and schemas for bot operations."""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3


@dataclass 
class RetryConfig:
    """Retry configuration."""
    max_attempts: int = 10
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0


@dataclass
class JobData:
    """Job data structure."""
    id: str
    a: int
    b: int
    operation: str = "sum"
    status: Optional[str] = None


@dataclass
class BotMetrics:
    """Bot metrics data structure."""
    bot_id: str
    state: str
    uptime_seconds: float
    startup_time_seconds: Optional[float]
    startup_attempts: int
    registration_attempts: int
    health_check_failures: int
    total_jobs_processed: int
    circuit_breakers: Dict[str, Dict[str, Any]]
    current_job: Optional[str]
    time_in_current_state: float