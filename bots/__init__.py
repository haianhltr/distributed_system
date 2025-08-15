"""Bot package for distributed job processing system."""

from .services.bot_service import BotService
from .config.settings import BotConfig, get_config

__version__ = "1.0.0"

__all__ = ["BotService", "BotConfig", "get_config"]