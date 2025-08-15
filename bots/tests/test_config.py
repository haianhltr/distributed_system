"""Test configuration management."""

import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import from config
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import BotConfig


def test_bot_config_defaults():
    """Test that BotConfig creates with sensible defaults."""
    # Clear any existing environment variables that might interfere
    env_vars_to_clear = [
        "BOT_ID", "MAIN_SERVER_URL", "HEARTBEAT_INTERVAL_MS", 
        "PROCESSING_DURATION_MS", "FAILURE_RATE", "MAX_STARTUP_ATTEMPTS"
    ]
    
    original_values = {}
    for var in env_vars_to_clear:
        original_values[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]
    
    try:
        # Create config from environment (should use defaults)
        config = BotConfig.from_environment()
        
        # Test basic structure
        assert hasattr(config, 'bot_id')
        assert hasattr(config, 'main_server_url')
        assert hasattr(config, 'heartbeat_interval')
        assert hasattr(config, 'processing_duration')
        assert hasattr(config, 'failure_rate')
        assert hasattr(config, 'max_startup_attempts')
        
        # Test default values
        assert config.main_server_url == "http://localhost:3001"
        assert config.heartbeat_interval == 30.0  # 30000ms / 1000
        assert config.processing_duration == 300.0  # 5 minutes
        assert config.failure_rate == 0.15  # 15%
        assert config.max_startup_attempts == 20
        
        # Test bot_id is generated (should start with "bot-")
        assert config.bot_id.startswith("bot-")
        assert len(config.bot_id) > 4  # Should have UUID part
        
        # Test circuit breaker defaults
        assert config.circuit_breaker_failure_threshold == 5
        assert config.circuit_breaker_recovery_timeout == 30.0
        assert config.circuit_breaker_half_open_max_calls == 3
        
        # Test retry defaults
        assert config.retry_max_attempts == 10
        assert config.retry_base_delay == 1.0
        assert config.retry_max_delay == 60.0
        assert config.retry_exponential_base == 2.0
        
        print("SUCCESS: BotConfig defaults test passed!")
        
    finally:
        # Restore original environment variables
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value


if __name__ == "__main__":
    test_bot_config_defaults()