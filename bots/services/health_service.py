"""Health check service for bot operations."""

import logging
from typing import List, Tuple, Callable, Awaitable
from services.http_client import HttpClient
from config.settings import BotConfig

logger = logging.getLogger(__name__)


class HealthService:
    """Service for performing comprehensive health checks."""
    
    def __init__(self, config: BotConfig, http_client: HttpClient):
        self.config = config
        self.http_client = http_client
        
    async def perform_all_checks(self) -> bool:
        """Perform all health checks."""
        checks = [
            ("Registration Verification", self._verify_registration),
            ("Server Connectivity", self._check_server_connectivity),
            ("Database Health", self._check_database_health)
        ]
        
        for check_name, check_func in checks:
            try:
                logger.debug(f"Performing health check: {check_name}")
                if not await check_func():
                    logger.warning(f"Health check failed: {check_name}")
                    return False
                logger.debug(f"Health check passed: {check_name}")
            except Exception as e:
                logger.error(f"Health check error ({check_name}): {e}")
                return False
        
        logger.info("All health checks passed")
        return True
    
    async def _verify_registration(self) -> bool:
        """Verify bot is properly registered."""
        try:
            bots = await self.http_client.get_bots_list()
            if bots is None:
                logger.warning("Failed to get bots list for registration verification")
                return False
            
            for bot in bots:
                if bot.get('id') == self.config.bot_id and not bot.get('deleted_at'):
                    logger.debug(f"Bot {self.config.bot_id} registration verified")
                    return True
            
            logger.warning(f"Bot {self.config.bot_id} not found in registered bots")
            return False
            
        except Exception as e:
            logger.error(f"Registration verification failed: {e}")
            return False
    
    async def _check_server_connectivity(self) -> bool:
        """Check main server connectivity."""
        try:
            result = await self.http_client.get_health_status("/healthz")
            if result:
                logger.debug("Server connectivity check passed")
            else:
                logger.warning("Server connectivity check failed")
            return result
        except Exception as e:
            logger.error(f"Server connectivity check failed: {e}")
            return False
    
    async def _check_database_health(self) -> bool:
        """Check database health via metrics endpoint."""
        try:
            metrics = await self.http_client.get_metrics()
            if metrics is None:
                logger.warning("Failed to get metrics for database health check")
                return False
            
            # Check if metrics contain expected data structure
            has_expected_structure = 'bots' in metrics and 'jobs' in metrics
            if has_expected_structure:
                logger.debug("Database health check passed")
            else:
                logger.warning("Database health check failed - missing expected data structure")
            
            return has_expected_structure
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    async def quick_connectivity_check(self) -> bool:
        """Perform a quick connectivity check."""
        return await self._check_server_connectivity()
    
    async def get_health_summary(self) -> dict:
        """Get a summary of health check results."""
        results = {}
        
        checks = [
            ("registration", self._verify_registration),
            ("connectivity", self._check_server_connectivity), 
            ("database", self._check_database_health)
        ]
        
        for check_name, check_func in checks:
            try:
                results[check_name] = await check_func()
            except Exception as e:
                logger.error(f"Health check {check_name} failed: {e}")
                results[check_name] = False
        
        results["overall"] = all(results.values())
        return results