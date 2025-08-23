"""Retry logic utilities."""

import asyncio
import logging
from typing import Callable, Any, Optional
from ..models.schemas import RetryConfig

logger = logging.getLogger(__name__)


class RetryHandler:
    """Handles retry logic with exponential backoff."""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        return min(delay, self.config.max_delay)
    
    async def execute_with_retry(
        self, 
        operation: Callable,
        operation_name: str = "operation",
        *args,
        **kwargs
    ) -> Any:
        """Execute operation with retry logic."""
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(operation):
                    result = await operation(*args, **kwargs)
                else:
                    result = operation(*args, **kwargs)
                
                if attempt > 1:
                    logger.info(f"{operation_name} succeeded on attempt {attempt}")
                
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"{operation_name} failed on attempt {attempt}: {e}")
                
                if attempt < self.config.max_attempts:
                    delay = self.calculate_delay(attempt)
                    logger.info(f"Retrying {operation_name} in {delay:.1f}s")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"{operation_name} failed after {self.config.max_attempts} attempts")
        
        # Re-raise the last exception if all attempts failed
        if last_exception:
            raise last_exception