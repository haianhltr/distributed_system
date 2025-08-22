"""Background task management for the distributed system."""

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog

from database import DatabaseManager
from datalake import DatalakeManager
from repositories import create_unit_of_work
from core.config import get_config


logger = structlog.get_logger(__name__)


class BackgroundTaskManager:
    """Manages all background tasks for the system."""
    
    def __init__(self, db_manager: DatabaseManager, datalake_manager: DatalakeManager):
        self.db = db_manager
        self.datalake = datalake_manager
        self.config = get_config()
        self._running = False
        self._tasks: list[asyncio.Task] = []
    
    async def start(self):
        """Start all background tasks."""
        if self._running:
            logger.warning("Background tasks already running")
            return
        
        self._running = True
        
        # Start auto job population
        self._tasks.append(asyncio.create_task(self._auto_populate_jobs()))
        
        # Start orphaned job recovery
        self._tasks.append(asyncio.create_task(self._job_recovery_loop()))
        
        logger.info("Background tasks started")
    
    async def stop(self):
        """Stop all background tasks."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for all tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
        logger.info("Background tasks stopped")
    
    async def _auto_populate_jobs(self):
        """Background task to automatically populate jobs."""
        while self._running:
            try:
                await asyncio.sleep(self.config.populate_interval_ms / 1000)
                
                if not self._running:
                    break
                
                logger.info("Auto-populating jobs...")
                
                async with create_unit_of_work(self.db.pool) as uow:
                    for _ in range(self.config.batch_size):
                        if not self._running:
                            break
                        
                        # Generate random job parameters
                        a = random.randint(0, 999)
                        operation = random.choice(['sum', 'subtract', 'multiply', 'divide'])
                        
                        # Prevent division by zero
                        if operation == 'divide':
                            b = random.randint(1, 999)
                        else:
                            b = random.randint(0, 999)
                        
                        await uow.jobs.create(a, b, operation)
                
                logger.info(f"Auto-created {self.config.batch_size} jobs with random operations")
                
            except asyncio.CancelledError:
                logger.info("Auto job population task cancelled")
                break
            except Exception as e:
                logger.error(f"Failed to auto-populate jobs: {e}")
                # Continue running even if one iteration fails
    
    async def _job_recovery_loop(self):
        """Background task to recover orphaned jobs."""
        while self._running:
            try:
                await self._recover_orphaned_jobs()
                await asyncio.sleep(60)  # Run every minute
                
            except asyncio.CancelledError:
                logger.info("Job recovery task cancelled")
                break
            except Exception as e:
                logger.error(f"Job recovery loop error: {e}")
                await asyncio.sleep(60)
    
    async def _recover_orphaned_jobs(self):
        """Recover jobs claimed by dead bots."""
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=5)
            
            async with create_unit_of_work(self.db.pool) as uow:
                # Find orphaned jobs
                orphaned_jobs = await uow.jobs.find_orphaned_jobs(cutoff)
                
                if orphaned_jobs:
                    for job in orphaned_jobs:
                        # Release job back to pending
                        await uow.jobs.release_to_pending(job['id'])
                        
                        # Increment attempts
                        await uow.execute_command("""
                            UPDATE jobs 
                            SET attempts = attempts + 1
                            WHERE id = $1
                        """, job['id'])
                        
                        logger.info(
                            "Recovered orphaned job", 
                            job_id=job['id'],
                            bot_id=job['claimed_by']
                        )
                
                if orphaned_jobs:
                    logger.info(f"Recovered {len(orphaned_jobs)} orphaned jobs")
                
        except Exception as e:
            logger.error(f"Orphaned job recovery failed: {e}")