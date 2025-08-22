"""Domain value objects for type safety and validation."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobId:
    """Value object for Job ID."""
    value: str
    
    def __post_init__(self):
        if not self.value or not isinstance(self.value, str):
            raise ValueError("Job ID must be a non-empty string")
    
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class BotId:
    """Value object for Bot ID."""
    value: str
    
    def __post_init__(self):
        if not self.value or not isinstance(self.value, str):
            raise ValueError("Bot ID must be a non-empty string")
    
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ProcessingDuration:
    """Value object for processing duration."""
    milliseconds: int
    
    def __post_init__(self):
        if self.milliseconds < 0:
            raise ValueError("Duration cannot be negative")
    
    @property
    def seconds(self) -> float:
        """Get duration in seconds."""
        return self.milliseconds / 1000.0
    
    @property
    def formatted(self) -> str:
        """Get human-readable formatted duration."""
        total_seconds = int(self.seconds)
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def __str__(self) -> str:
        return self.formatted