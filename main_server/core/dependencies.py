"""Dependency injection container."""

from typing import Optional
import structlog

from .config import Config

try:
    from database import DatabaseManager
    from datalake import DatalakeManager
    from cleanup_service import CleanupService, CleanupScheduler
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False


class Dependencies:
    """Dependency injection container for application services."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = structlog.get_logger(__name__)
        
        if DATABASE_AVAILABLE:
            # Initialize core dependencies
            self.db_manager = DatabaseManager(config.database_url)
            self.datalake_manager = DatalakeManager(config.datalake_path)
            
            # Initialize cleanup services
            self.cleanup_service = CleanupService(self.db_manager)
            self.cleanup_scheduler = CleanupScheduler(self.cleanup_service)
        else:
            self.db_manager = None
            self.datalake_manager = None
            self.cleanup_service = None
            self.cleanup_scheduler = None
        
    async def initialize(self):
        """Initialize all async dependencies."""
        if DATABASE_AVAILABLE and self.db_manager:
            await self.db_manager.initialize()
            await self.cleanup_scheduler.start()
            self.logger.info("Dependencies initialized successfully")
        else:
            self.logger.warning("Database dependencies not available - running in test mode")
        
    async def cleanup(self):
        """Clean up all dependencies."""
        if DATABASE_AVAILABLE and self.db_manager:
            await self.cleanup_scheduler.stop()
            await self.db_manager.close()
            self.logger.info("Dependencies cleaned up successfully")
        else:
            self.logger.info("No dependencies to clean up")


# Global dependencies instance
_dependencies: Optional[Dependencies] = None


def get_dependencies() -> Dependencies:
    """Get the global dependencies instance."""
    global _dependencies
    if _dependencies is None:
        from .config import get_config
        _dependencies = Dependencies(get_config())
    return _dependencies