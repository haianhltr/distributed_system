"""Bot configuration management."""

import os
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class BotConfig:
    """Bot configuration with environment variable support."""
    
    # Identity
    bot_id: str
    
    # Server connection
    main_server_url: str
    
    # Timing configuration (in seconds)
    heartbeat_interval: float
    processing_duration: float
    
    # Behavior
    failure_rate: float
    max_startup_attempts: int
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0
    circuit_breaker_half_open_max_calls: int = 3
    
    # Retry configuration
    retry_max_attempts: int = 10
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    retry_exponential_base: float = 2.0
    
    @classmethod
    def from_environment(cls) -> "BotConfig":
        """Create configuration from environment variables."""
        return cls(
            bot_id=os.environ.get("BOT_ID", f"bot-{uuid.uuid4()}"),
            main_server_url=os.environ.get("MAIN_SERVER_URL", "http://localhost:3001"),
            heartbeat_interval=int(os.environ.get("HEARTBEAT_INTERVAL_MS", "30000")) / 1000,
            processing_duration=int(os.environ.get("PROCESSING_DURATION_MS", str(5 * 60 * 1000))) / 1000,
            failure_rate=float(os.environ.get("FAILURE_RATE", "0.15")),
            max_startup_attempts=int(os.environ.get("MAX_STARTUP_ATTEMPTS", "20")),
            
            # Circuit breaker settings
            circuit_breaker_failure_threshold=int(os.environ.get("CB_FAILURE_THRESHOLD", "5")),
            circuit_breaker_recovery_timeout=float(os.environ.get("CB_RECOVERY_TIMEOUT", "30.0")),
            circuit_breaker_half_open_max_calls=int(os.environ.get("CB_HALF_OPEN_MAX_CALLS", "3")),
            
            # Retry settings
            retry_max_attempts=int(os.environ.get("RETRY_MAX_ATTEMPTS", "10")),
            retry_base_delay=float(os.environ.get("RETRY_BASE_DELAY", "1.0")),
            retry_max_delay=float(os.environ.get("RETRY_MAX_DELAY", "60.0")),
            retry_exponential_base=float(os.environ.get("RETRY_EXPONENTIAL_BASE", "2.0"))
        )


# Global config instance
_config: Optional[BotConfig] = None


def get_config() -> BotConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = BotConfig.from_environment()
    return _config