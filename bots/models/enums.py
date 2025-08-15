"""Enumerations for bot states and status."""

from enum import Enum


class BotState(Enum):
    """Bot lifecycle states."""
    INITIALIZING = "initializing"
    REGISTERING = "registering"
    HEALTH_CHECK = "health_check"
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"