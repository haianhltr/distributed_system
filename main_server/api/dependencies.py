"""FastAPI dependency injection helpers."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.dependencies import get_dependencies
from core.config import get_config
from core.exceptions import AuthenticationError, service_error_handler
from services import JobService, BotService, MetricsService, AdminService
from database import DatabaseManager
from datalake import DatalakeManager


security = HTTPBearer()


async def get_database() -> DatabaseManager:
    """Get database manager instance."""
    deps = get_dependencies()
    if not deps.db_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    return deps.db_manager


async def get_datalake() -> DatalakeManager:
    """Get datalake manager instance."""
    deps = get_dependencies()
    if not deps.datalake_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Datalake not available"
        )
    return deps.datalake_manager


async def get_job_service(
    db: DatabaseManager = Depends(get_database),
    datalake: DatalakeManager = Depends(get_datalake)
) -> JobService:
    """Get job service instance."""
    return JobService(db, datalake)


async def get_bot_service(
    db: DatabaseManager = Depends(get_database)
) -> BotService:
    """Get bot service instance."""
    return BotService(db)


async def get_metrics_service(
    db: DatabaseManager = Depends(get_database),
    datalake: DatalakeManager = Depends(get_datalake)
) -> MetricsService:
    """Get metrics service instance."""
    return MetricsService(db, datalake)


async def get_admin_service(
    db: DatabaseManager = Depends(get_database)
) -> AdminService:
    """Get admin service instance."""
    deps = get_dependencies()
    return AdminService(db, deps.cleanup_scheduler)


async def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """Verify admin authentication token."""
    config = get_config()
    if credentials.credentials != config.admin_token:
        raise service_error_handler(
            AuthenticationError("Invalid authentication credentials")
        )
    return credentials.credentials