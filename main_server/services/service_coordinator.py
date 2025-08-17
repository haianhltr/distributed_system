"""Service coordinator for orchestrating all system services."""

import asyncio
from typing import Optional
import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from services.bot_service import BotService
from services.job_service import JobService
from services.monitoring_service import MonitoringService, MonitoringConfig

logger = structlog.get_logger(__name__)


class ServiceCoordinator:
    """Coordinates all system services with unified lifecycle management."""
    
    def __init__(self, db_manager: DatabaseManager, datalake_manager: DatalakeManager):
        self.db_manager = db_manager
        self.datalake_manager = datalake_manager
        
        # Initialize core services
        self.bots = BotService(db_manager)
        self.jobs = JobService(db_manager, datalake_manager)
        self.monitoring = MonitoringService(db_manager, self.jobs, self.bots)
        
        # Service lifecycle state
        self._initialized = False
        self._running = False
        
        logger.info("Service coordinator created")
    
    def initialize(self, monitoring_config: Optional[MonitoringConfig] = None):
        """Initialize all services."""
        if self._initialized:
            logger.warning("Service coordinator already initialized")
            return
        
        try:
            # Initialize monitoring with configuration
            self.monitoring.initialize(monitoring_config)
            
            self._initialized = True
            logger.info("Service coordinator initialized")
            
        except Exception as e:
            logger.error("Failed to initialize service coordinator", error=str(e))
            raise
    
    async def start(self):
        """Start all services."""
        if not self._initialized:
            raise RuntimeError("Service coordinator not initialized")
        
        if self._running:
            logger.warning("Service coordinator already running")
            return
        
        try:
            # Start monitoring service
            await self.monitoring.start()
            
            self._running = True
            logger.info("Service coordinator started")
            
        except Exception as e:
            logger.error("Failed to start service coordinator", error=str(e))
            raise
    
    async def stop(self):
        """Stop all services."""
        if not self._running:
            logger.info("Service coordinator not running")
            return
        
        try:
            # Stop monitoring service
            await self.monitoring.stop()
            
            self._running = False
            logger.info("Service coordinator stopped")
            
        except Exception as e:
            logger.error("Error stopping service coordinator", error=str(e))
            # Continue with shutdown even if there's an error
            self._running = False
    
    def get_health_status(self) -> dict:
        """Get overall health status of all services."""
        return {
            "coordinator": {
                "initialized": self._initialized,
                "running": self._running
            },
            "services": {
                "bot_service": "active",
                "job_service": "active",
                "monitoring": self.monitoring.get_stats()
            },
            "database": "connected",  # Could add actual DB health check
            "datalake": "connected"   # Could add actual datalake health check
        }
    
    async def run_monitoring_check(self) -> list:
        """Run a manual monitoring check across all monitors."""
        if not self._initialized:
            raise RuntimeError("Service coordinator not initialized")
        
        return await self.monitoring.run_manual_check()
    
    def get_monitoring_stats(self) -> dict:
        """Get monitoring system statistics."""
        if not self._initialized:
            return {"status": "not_initialized"}
        
        return self.monitoring.get_stats()


# Global service coordinator instance
_service_coordinator: Optional[ServiceCoordinator] = None


def create_service_coordinator(
    db_manager: DatabaseManager, 
    datalake_manager: DatalakeManager,
    monitoring_config: Optional[MonitoringConfig] = None
) -> ServiceCoordinator:
    """Create and initialize the global service coordinator."""
    global _service_coordinator
    
    if _service_coordinator is not None:
        logger.warning("Service coordinator already exists")
        return _service_coordinator
    
    _service_coordinator = ServiceCoordinator(db_manager, datalake_manager)
    _service_coordinator.initialize(monitoring_config)
    
    return _service_coordinator


def get_service_coordinator() -> Optional[ServiceCoordinator]:
    """Get the current service coordinator instance."""
    return _service_coordinator


async def start_services():
    """Start all services through the coordinator."""
    coordinator = get_service_coordinator()
    if coordinator:
        await coordinator.start()
    else:
        logger.error("No service coordinator available to start")


async def stop_services():
    """Stop all services through the coordinator."""
    coordinator = get_service_coordinator()
    if coordinator:
        await coordinator.stop()
    else:
        logger.info("No service coordinator to stop")