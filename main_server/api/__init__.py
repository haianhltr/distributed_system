"""API routes and handlers."""

from .jobs import router as jobs_router
from .bots import router as bots_router
from .metrics import router as metrics_router
from .admin import router as admin_router
from .health import router as health_router

__all__ = [
    "jobs_router",
    "bots_router",
    "metrics_router", 
    "admin_router",
    "health_router"
]