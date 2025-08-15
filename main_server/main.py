"""Main application entry point with refactored architecture."""

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_config
from core.dependencies import get_dependencies
from core.exceptions import (
    ServiceError, ValidationError, NotFoundError, 
    ConflictError, AuthenticationError
)
from api import (
    health_router, jobs_router, bots_router, 
    metrics_router, admin_router
)


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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()
    
    app = FastAPI(
        title="Distributed Job Processing System",
        version="1.0.0",
        description="A distributed system for processing mathematical operations"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(bots_router)
    app.include_router(metrics_router)
    app.include_router(admin_router)
    
    return app


app = create_app()


# Background tasks
async def auto_populate_jobs():
    """Background task to automatically populate jobs."""
    config = get_config()
    deps = get_dependencies()
    
    while True:
        try:
            await asyncio.sleep(config.populate_interval_ms / 1000)  # Convert to seconds
            
            logger.info("Auto-populating jobs...")
            
            async with deps.db_manager.get_connection() as conn:
                async with conn.transaction():
                    for i in range(config.batch_size):
                        job_id = str(uuid.uuid4())
                        a = random.randint(0, 999)
                        b = random.randint(0, 999)
                        
                        await conn.execute("""
                            INSERT INTO jobs (id, a, b, status, created_at) 
                            VALUES ($1, $2, $3, 'pending', CURRENT_TIMESTAMP)
                        """, job_id, a, b)
            
            logger.info("Auto-created jobs", count=config.batch_size)
            
        except Exception as e:
            logger.error("Failed to auto-populate jobs", error=str(e))


async def job_recovery_loop():
    """Background task to recover orphaned jobs."""
    deps = get_dependencies()
    
    while True:
        try:
            await recover_orphaned_jobs(deps)
            await asyncio.sleep(60)  # Run every minute
        except Exception as e:
            logger.error("Job recovery loop error", error=str(e))
            await asyncio.sleep(60)


async def recover_orphaned_jobs(deps):
    """Recover jobs claimed by dead bots."""
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        
        async with deps.db_manager.get_connection() as conn:
            # Find jobs claimed by bots that haven't sent heartbeat
            orphaned_jobs = await conn.fetch("""
                SELECT j.id, j.claimed_by 
                FROM jobs j
                JOIN bots b ON j.claimed_by = b.id
                WHERE j.status = 'claimed' 
                AND b.last_heartbeat_at < $1
                AND b.deleted_at IS NULL
            """, cutoff)
            
            if orphaned_jobs:
                async with conn.transaction():
                    for job in orphaned_jobs:
                        await conn.execute("""
                            UPDATE jobs 
                            SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                                attempts = attempts + 1
                            WHERE id = $1
                        """, job['id'])
                        
                        logger.info("Recovered orphaned job", job_id=job['id'], 
                                   bot_id=job['claimed_by'])
            
                logger.info("Recovered orphaned jobs", count=len(orphaned_jobs))
                
    except Exception as e:
        logger.error("Orphaned job recovery failed", error=str(e))


@app.on_event("startup")
async def startup_event():
    """Initialize application dependencies and start background tasks."""
    try:
        deps = get_dependencies()
        await deps.initialize()
        
        # Start background tasks
        asyncio.create_task(auto_populate_jobs())
        asyncio.create_task(job_recovery_loop())
        
        logger.info("Application started successfully")
        
    except Exception as e:
        logger.error("Startup failed", error=str(e))
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up application resources."""
    try:
        deps = get_dependencies()
        await deps.cleanup()
        logger.info("Application shutdown completed")
        
    except Exception as e:
        logger.error("Shutdown failed", error=str(e))


if __name__ == "__main__":
    config = get_config()
    
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.reload
    )