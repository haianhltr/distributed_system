"""Main entry point for the refactored bot application."""

import asyncio
import signal
import logging
from typing import Optional

from config.settings import get_config
from services.bot_service import BotService
from utils.logging import setup_logging

# Global bot instance for signal handling
bot_instance: Optional[BotService] = None


async def shutdown_handler():
    """Handle graceful shutdown."""
    if bot_instance:
        await bot_instance.stop()


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger = logging.getLogger(__name__)
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    asyncio.create_task(shutdown_handler())


async def main():
    """Main entry point."""
    global bot_instance
    
    # Set up logging
    logger = setup_logging()
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Load configuration
        config = get_config()
        logger.info(f"Starting bot with ID: {config.bot_id}")
        
        # Create and start bot service
        bot_instance = BotService(config)
        await bot_instance.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        raise
    finally:
        if bot_instance:
            await bot_instance.stop()


if __name__ == "__main__":
    asyncio.run(main())