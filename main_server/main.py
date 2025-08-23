"""
Refactored distributed job processing system main application.

This is a clean, minimal main.py that follows proper software architecture principles:
- Layered architecture (API -> Service -> Repository -> Database)
- Dependency injection
- Separation of concerns
- Proper error handling
- Domain-driven design
"""

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from core.config import get_config
from core.dependencies import get_dependencies
from core.exceptions import ServiceError, service_error_handler

# Import API routers
from api.jobs import router as jobs_router
from api.bots import router as bots_router
from api.metrics import router as metrics_router
from api.health import router as health_router
from api.admin import router as admin_router
from api.auth import router as auth_router


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    config = get_config()
    logger.info("Starting distributed job processing system", version="2.0.0")
    
    # Initialize dependencies
    deps = get_dependencies()
    await deps.initialize()
    
    # Start background tasks
    from services.background_tasks import BackgroundTaskManager
    background_manager = BackgroundTaskManager(deps.db_manager, deps.datalake_manager)
    await background_manager.start()
    
    logger.info("Application started successfully")
    
    yield
    
    # Cleanup
    await background_manager.stop()
    await deps.cleanup()
    logger.info("Application shutdown completed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()
    
    app = FastAPI(
        title="Distributed Job Processing System",
        version="2.0.0",
        description="A refactored distributed system with clean architecture",
        lifespan=lifespan
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Configure properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register exception handlers
    @app.exception_handler(ServiceError)
    async def service_exception_handler(request, exc: ServiceError):
        return service_error_handler(exc)
    
    # Include API routers
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/v1")
    app.include_router(jobs_router)
    app.include_router(bots_router, prefix="/v1")
    app.include_router(metrics_router)
    app.include_router(admin_router)
    
    return app


app = create_app()


if __name__ == "__main__":
    config = get_config()
    uvicorn.run(
        "main_clean:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
        log_config=None  # Use our custom logging
    )