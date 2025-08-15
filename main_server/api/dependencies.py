"""FastAPI dependency injection helpers."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.dependencies import get_dependencies
from core.config import get_config
from services import JobService, BotService, MetricsService, AdminService


security = HTTPBearer()


async def get_job_service() -> JobService:
    """Get job service instance."""
    deps = get_dependencies()
    return JobService(deps.db_manager, deps.datalake_manager)


async def get_bot_service() -> BotService:
    """Get bot service instance."""
    deps = get_dependencies()
    return BotService(deps.db_manager)


async def get_metrics_service() -> MetricsService:
    """Get metrics service instance."""
    deps = get_dependencies()
    return MetricsService(deps.db_manager, deps.datalake_manager)


async def get_admin_service() -> AdminService:
    """Get admin service instance."""
    deps = get_dependencies()
    return AdminService(deps.db_manager, deps.cleanup_scheduler)


async def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    admin_service: AdminService = Depends(get_admin_service)
) -> str:
    """Verify admin authentication token."""
    config = get_config()
    admin_service.verify_admin_token(credentials.credentials, config.admin_token)
    return credentials.credentials