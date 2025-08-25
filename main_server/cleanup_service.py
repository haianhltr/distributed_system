import asyncio
import os
import subprocess
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import asyncpg
import structlog
from main_server.database import DatabaseManager

logger = structlog.get_logger(__name__)


class CleanupService:
    """Automated cleanup service for orphaned resources"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.config = {
            "bot_retention_days": int(os.environ.get("BOT_RETENTION_DAYS", "7")),
            "container_cleanup_enabled": os.environ.get("CONTAINER_CLEANUP_ENABLED", "true").lower() == "true",
            "cleanup_interval_hours": int(os.environ.get("CLEANUP_INTERVAL_HOURS", "6")),
            "dry_run": os.environ.get("CLEANUP_DRY_RUN", "false").lower() == "true"
        }
        self._running = False
        self._cleanup_history = []  # Store last N cleanup runs
        self._max_history = 10
        
    async def start(self):
        """Start the cleanup service background task"""
        if self._running:
            logger.warning("Cleanup service already running")
            return
            
        self._running = True
        asyncio.create_task(self._cleanup_loop())
        logger.info("Cleanup service started", config=self.config)
        
    async def stop(self):
        """Stop the cleanup service"""
        self._running = False
        logger.info("Cleanup service stopped")
        
    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically"""
        while self._running:
            try:
                await self.run_cleanup()
                await asyncio.sleep(self.config["cleanup_interval_hours"] * 3600)
            except Exception as e:
                logger.error("Cleanup loop error", error=str(e))
                await asyncio.sleep(300)  # Retry after 5 minutes on error
                
    async def run_cleanup(self) -> Dict[str, Any]:
        """Run all cleanup tasks"""
        logger.info("Starting cleanup run", dry_run=self.config["dry_run"])
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "dry_run": self.config["dry_run"],
            "database_cleanup": await self._cleanup_database(),
            "container_cleanup": await self._cleanup_containers() if self.config["container_cleanup_enabled"] else None
        }
        
        # Store in history
        self._add_to_history(results)
        
        logger.info("Cleanup run completed", results=results)
        return results
        
    async def _cleanup_database(self) -> Dict[str, Any]:
        """Clean up old deleted bot records"""
        retention_date = datetime.utcnow() - timedelta(days=self.config["bot_retention_days"])
        
        async with self.db.get_connection() as conn:
            # First, count records to be deleted
            count_query = """
                SELECT COUNT(*) 
                FROM bots 
                WHERE deleted_at IS NOT NULL 
                AND deleted_at < $1
            """
            count = await conn.fetchval(count_query, retention_date)
            
            if self.config["dry_run"]:
                # In dry run, just return what would be deleted
                records = await conn.fetch("""
                    SELECT id, deleted_at 
                    FROM bots 
                    WHERE deleted_at IS NOT NULL 
                    AND deleted_at < $1
                    LIMIT 100
                """, retention_date)
                
                return {
                    "action": "dry_run",
                    "would_delete": count,
                    "sample_records": [dict(r) for r in records[:10]]
                }
            else:
                # Actually delete the records
                deleted = await conn.fetch("""
                    DELETE FROM bots 
                    WHERE deleted_at IS NOT NULL 
                    AND deleted_at < $1
                    RETURNING id, deleted_at
                """, retention_date)
                
                # Also clean up orphaned results
                orphan_results = await conn.execute("""
                    DELETE FROM results 
                    WHERE processed_by NOT IN (SELECT id FROM bots)
                """)
                
                return {
                    "action": "deleted",
                    "deleted_bots": len(deleted),
                    "orphaned_results_cleaned": orphan_results.split()[-1] if orphan_results else 0,
                    "retention_date": retention_date.isoformat()
                }
                
    async def _cleanup_containers(self) -> Dict[str, Any]:
        """Clean up orphaned Docker containers"""
        results = {
            "stopped_containers": [],
            "active_bots": [],
            "cleaned": []
        }
        
        try:
            # Get list of active bots from database
            async with self.db.get_connection() as conn:
                active_bots = await conn.fetch("""
                    SELECT id 
                    FROM bots 
                    WHERE deleted_at IS NULL
                """)
                results["active_bots"] = [bot["id"] for bot in active_bots]
            
            # Get all bot containers
            # Check if we're in a container or on host
            if os.path.exists("/.dockerenv"):
                # We're in a container, skip Docker operations
                logger.warning("Container cleanup disabled - running inside Docker container")
                results["error"] = "Container cleanup not available from within container"
                return results
            
            cmd = ["docker", "ps", "-a", "--format", "{{.Names}}:{{.State}}:{{.ID}}", "--filter", "name=bot-"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error("Failed to list containers", error=stderr.decode())
                return results
                
            # Parse container info
            containers = []
            for line in stdout.decode().strip().split('\n'):
                if line:
                    parts = line.split(':')
                    if len(parts) >= 3:
                        name, state, container_id = parts[0], parts[1], parts[2]
                        containers.append({
                            "name": name,
                            "state": state,
                            "id": container_id
                        })
            
            # Identify orphaned containers
            for container in containers:
                bot_id = self._extract_bot_id(container["name"])
                
                if container["state"] == "exited":
                    results["stopped_containers"].append(container["name"])
                    
                    # Check if this bot exists in database
                    if bot_id not in results["active_bots"]:
                        if not self.config["dry_run"]:
                            # Remove the container
                            await self._remove_container(container["id"])
                            results["cleaned"].append({
                                "container": container["name"],
                                "action": "removed"
                            })
                        else:
                            results["cleaned"].append({
                                "container": container["name"],
                                "action": "would_remove"
                            })
                            
        except Exception as e:
            logger.error("Container cleanup error", error=str(e))
            results["error"] = str(e)
            
        return results
        
    def _extract_bot_id(self, container_name: str) -> str:
        """Extract bot ID from container name"""
        # Handle different naming patterns
        # e.g., "bot-docker-1", "bot-dynamic-799-0", "distributed-system-test-bot-1-1"
        if container_name.startswith("distributed-system-test-"):
            # Docker Compose format
            parts = container_name.replace("distributed-system-test-", "").split("-")
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}-{parts[2]}"
        return container_name
        
    async def _remove_container(self, container_id: str):
        """Remove a Docker container"""
        cmd = ["docker", "rm", "-f", container_id]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode == 0:
            logger.info("Container removed", container_id=container_id)
        else:
            logger.error("Failed to remove container", container_id=container_id)
    
    def _add_to_history(self, results: Dict[str, Any]):
        """Add cleanup results to history"""
        # Calculate summary statistics
        summary = {
            "timestamp": results["timestamp"],
            "dry_run": results["dry_run"],
            "deleted_bots": 0,
            "cleaned_containers": 0,
            "errors": []
        }
        
        if results.get("database_cleanup"):
            db_cleanup = results["database_cleanup"]
            if db_cleanup.get("action") == "deleted":
                summary["deleted_bots"] = db_cleanup.get("deleted_bots", 0)
            elif db_cleanup.get("action") == "dry_run":
                summary["deleted_bots"] = db_cleanup.get("would_delete", 0)
                
        if results.get("container_cleanup"):
            container_cleanup = results["container_cleanup"]
            summary["cleaned_containers"] = len(container_cleanup.get("cleaned", []))
            if container_cleanup.get("error"):
                summary["errors"].append(container_cleanup["error"])
                
        # Add to history, keeping only last N entries
        self._cleanup_history.append(summary)
        if len(self._cleanup_history) > self._max_history:
            self._cleanup_history.pop(0)
            
    def get_history(self) -> List[Dict[str, Any]]:
        """Get cleanup history"""
        return list(reversed(self._cleanup_history))  # Most recent first


class CleanupScheduler:
    """Manages scheduled cleanup tasks"""
    
    def __init__(self, cleanup_service: CleanupService):
        self.cleanup_service = cleanup_service
        self.tasks = []
        
    async def start(self):
        """Start scheduled cleanup tasks"""
        # Schedule immediate cleanup on startup
        task = asyncio.create_task(self._initial_cleanup())
        self.tasks.append(task)
        
        # Start the periodic cleanup
        await self.cleanup_service.start()
        
    async def stop(self):
        """Stop all scheduled tasks"""
        await self.cleanup_service.stop()
        for task in self.tasks:
            task.cancel()
            
    async def _initial_cleanup(self):
        """Run initial cleanup on startup"""
        await asyncio.sleep(60)  # Wait 1 minute after startup
        logger.info("Running initial cleanup")
        await self.cleanup_service.run_cleanup()
        
    async def force_cleanup(self) -> Dict[str, Any]:
        """Force an immediate cleanup run"""
        logger.info("Force cleanup requested")
        return await self.cleanup_service.run_cleanup()