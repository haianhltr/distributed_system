"""Application configuration management."""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration with environment variable support."""
    
    # Job processing
    populate_interval_ms: int = Field(default=600000, env="POPULATE_INTERVAL_MS")  # 10 minutes
    batch_size: int = Field(default=5, env="BATCH_SIZE")
    
    # Security
    admin_token: str = Field(default="admin-secret-token", env="ADMIN_TOKEN")
    
    # Database
    database_url: str = Field(
        default="postgresql://ds_user:ds_password@localhost:5432/distributed_system",
        env="DATABASE_URL"
    )
    
    # Storage
    datalake_path: str = Field(default="datalake/data", env="DATALAKE_PATH")
    
    # Cleanup service
    bot_retention_days: int = Field(default=7, env="BOT_RETENTION_DAYS")
    container_cleanup_enabled: bool = Field(default=True, env="CONTAINER_CLEANUP_ENABLED")
    cleanup_interval_hours: int = Field(default=6, env="CLEANUP_INTERVAL_HOURS")
    cleanup_dry_run: bool = Field(default=False, env="CLEANUP_DRY_RUN")
    
    # Server
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=3001, env="PORT")
    reload: bool = Field(default=True, env="RELOAD")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config