"""Bot management business logic."""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import structlog

from main_server.database import DatabaseManager
from main_server.repositories import create_unit_of_work
from main_server.domain import Bot, BotStatus, Operation, ProcessingDuration
from main_server.models.schemas import BotRegister, BotHeartbeat, BotAssignOperation
from main_server.core.exceptions import NotFoundError, ValidationError, ConflictError, BusinessRuleViolation


logger = structlog.get_logger(__name__)


class BotService:
    """Service for bot management operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
    async def register_bot(self, bot_data: BotRegister, idempotency_key: str) -> Dict[str, Any]:
        """Register a new bot with full contract response."""
        bot_key = bot_data.bot_key
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Check idempotency first
                existing_response = await self._check_idempotency(uow, idempotency_key)
                if existing_response:
                    return existing_response
                
                # Generate bot ID and create bot
                import uuid
                bot_id = f"b_{uuid.uuid4().hex[:5].upper()}"
                
                # Register bot in database
                bot = await uow.bots.register(bot_key, bot_id)
                
                # Create session
                session_id = f"s_{uuid.uuid4().hex[:5].upper()}"
                expires_in_sec = 900  # 15 minutes
                heartbeat_interval_sec = 30
                
                # Build full response per contract
                registration_response = {
                    "bot_id": bot_id,
                    "registered_at": datetime.utcnow().isoformat() + "Z",
                    "session": {
                        "session_id": session_id,
                        "expires_in_sec": expires_in_sec,
                        "heartbeat_interval_sec": heartbeat_interval_sec
                    },
                    "assignment": {
                        "operation": None,
                        "queue": None,
                        "max_concurrency": bot_data.capabilities.max_concurrency
                    },
                    "policy": {
                        "rate_limits": {
                            "claim_rps": 1
                        },
                        "backoff": {
                            "min_ms": 200,
                            "max_ms": 5000,
                            "jitter": True
                        }
                    },
                    "endpoints": {
                        "heartbeat": "/v1/bots/heartbeat",
                        "claim": "/v1/jobs/claim",
                        "report": "/v1/jobs/report"
                    },
                    "server": {
                        "region": "us-east-1",
                        "version": "2025.08.22.1"
                    }
                }
                
                # Store idempotency record
                await self._store_idempotency(uow, idempotency_key, 200, registration_response)
                
                logger.info("Bot registered", bot_id=bot_id, bot_key=bot_key)
                return registration_response
                
        except Exception as e:
            logger.error("Failed to register bot", bot_key=bot_key, error=str(e))
            raise ValidationError(f"Registration failed: {str(e)}")
    
    async def _check_idempotency(self, uow, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Check if this is a duplicate request."""
        # Simple implementation - in production use proper idempotency store
        # For now, return None (no duplicates)
        return None
    
    async def _store_idempotency(self, uow, idempotency_key: str, status: int, response: Dict[str, Any]):
        """Store idempotency record."""
        # Simple implementation - in production store in database
        # For now, just log
        logger.debug(f"Stored idempotency record: {idempotency_key}, status: {status}")
    
    async def update_heartbeat(self, heartbeat_data: BotHeartbeat) -> Dict[str, str]:
        """Update bot heartbeat."""
        bot_id = heartbeat_data.bot_id
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                success = await uow.bots.update_heartbeat(bot_id)
                
                if not success:
                    raise NotFoundError("Bot", bot_id)
                
                return {"status": "ok"}
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to update heartbeat", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to update heartbeat: {str(e)}")
    
    async def assign_operation(self, bot_id: str, assignment: BotAssignOperation) -> Dict[str, Any]:
        """Assign an operation to a bot."""
        operation = assignment.operation
        
        # Validate operation
        try:
            operation_enum = Operation(operation)
        except ValueError:
            raise ValidationError(f"Invalid operation: {operation}")
        
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                success = await uow.bots.assign_operation(bot_id, operation)
                if not success:
                    raise ConflictError("Failed to assign operation")
                
                logger.info(f"Assigned operation '{operation}' to bot {bot_id}")
                
                return {
                    "status": "assigned",
                    "bot_id": bot_id,
                    "operation": operation,
                    "message": f"Bot {bot_id} has been assigned to {operation} operations"
                }
                
        except (NotFoundError, ConflictError):
            raise
        except Exception as e:
            logger.error(f"Failed to assign operation to bot {bot_id}: {e}")
            raise ValidationError(f"Failed to assign operation: {str(e)}")
    
    async def get_bots(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all bots with job processing duration and lifecycle status."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                bots = await uow.bots.find_active(include_deleted)
                
                # Format duration fields
                for bot in bots:
                    if bot.get('processing_duration_seconds'):
                        duration_ms = int(bot['processing_duration_seconds'] * 1000)
                        duration = ProcessingDuration(duration_ms)
                        bot['processing_duration_formatted'] = duration.formatted
                    else:
                        bot['processing_duration_seconds'] = None
                        bot['processing_duration_formatted'] = None
                    
                    if bot.get('seconds_since_heartbeat'):
                        seconds = int(bot['seconds_since_heartbeat'])
                        duration = ProcessingDuration(seconds * 1000)
                        bot['heartbeat_age_formatted'] = duration.formatted + " ago"
                    else:
                        bot['heartbeat_age_formatted'] = None
                    
                    if bot.get('seconds_since_deleted'):
                        seconds = int(bot['seconds_since_deleted'])
                        duration = ProcessingDuration(seconds * 1000)
                        bot['deleted_age_formatted'] = duration.formatted + " ago"
                    else:
                        bot['deleted_age_formatted'] = None
                
                return bots
                
        except Exception as e:
            logger.error("Failed to get bots", error=str(e))
            raise ValidationError(f"Failed to retrieve bots: {str(e)}")
    
    async def delete_bot(self, bot_id: str) -> Dict[str, str]:
        """Delete a bot and handle its current job."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                # Handle current job if exists
                if bot.get('current_job_id'):
                    job = await uow.jobs.find_by_id(bot['current_job_id'])
                    
                    if job:
                        if job['status'] == 'processing':
                            # Mark job as failed due to bot termination
                            await uow.jobs.fail(bot['current_job_id'], bot_id, 'Bot terminated')
                        elif job['status'] == 'claimed':
                            # Return job to pending
                            await uow.jobs.release_to_pending(bot['current_job_id'])
                
                # Soft delete the bot
                await uow.bots.soft_delete(bot_id)
            
            logger.info("Bot deleted", bot_id=bot_id)
            return {"status": "deleted"}
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to delete bot", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to delete bot: {str(e)}")
    
    async def get_bot_stats(self, bot_id: str, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive performance stats and history for a bot."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Get bot to verify it exists
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                # Get stats
                stats = await uow.results.get_bot_stats(bot_id, hours)
                hourly_stats = await uow.results.get_hourly_stats(bot_id)
                recent_jobs = await uow.results.find_by_bot(bot_id, hours, limit=50)
                
                result = {
                    "bot_id": bot_id,
                    "period_hours": hours,
                    **stats
                }
                
                if stats['total_jobs'] > 0:
                    result["success_rate"] = (stats["succeeded"] / stats["total_jobs"]) * 100
                else:
                    result["success_rate"] = 0.0
                
                # Format hourly performance
                result["hourly_performance"] = [
                    {
                        "hour": row["hour"].isoformat(),
                        "total": row["total"],
                        "succeeded": row["succeeded"],
                        "failed": row["failed"],
                        "success_rate": (row["succeeded"] / row["total"]) * 100 if row["total"] > 0 else 0,
                        "avg_duration_ms": row["avg_duration_ms"]
                    }
                    for row in hourly_stats
                ]
                
                # Format recent jobs
                result["recent_jobs"] = [
                    {
                        **job,
                        "duration_formatted": ProcessingDuration(job["duration_ms"]).formatted if job.get("duration_ms") else None,
                        "processed_at": job["processed_at"].isoformat() if job.get("processed_at") else None
                    }
                    for job in recent_jobs
                ]
                
                return result
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to get bot stats", bot_id=bot_id, error=str(e))
            raise ValidationError(f"Failed to retrieve bot stats: {str(e)}")
    
    async def reset_bot_state(self, bot_id: str) -> Dict[str, Any]:
        """Reset bot state to clear stale job assignments."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                released_job_id = None
                
                # Reset bot state
                bot_state = await uow.bots.reset_bot_state(bot_id)
                if bot_state.get('current_job_id'):
                    released_job_id = bot_state['current_job_id']
                
                # Release any jobs claimed by this bot
                query = """
                    UPDATE jobs 
                    SET status = 'pending', 
                        claimed_by = NULL, 
                        claimed_at = NULL,
                        started_at = NULL,
                        error = CASE 
                            WHEN error IS NULL THEN 'Bot reset - job released'
                            ELSE error || ' | Bot reset - job released'
                        END
                    WHERE claimed_by = $1 AND status IN ('claimed', 'processing')
                    RETURNING id
                """
                released_jobs = await uow.execute_query(query, bot_id)
                
                logger.info(f"Reset bot state: {bot_id}, released {len(released_jobs)} jobs")
                
                return {
                    "status": "reset",
                    "bot_id": bot_id,
                    "released_job_id": released_job_id,
                    "jobs_released": len(released_jobs)
                }
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to reset bot {bot_id}: {e}")
            raise ValidationError(f"Reset failed: {str(e)}")
    
    async def restart_bot(self, bot_id: str) -> Dict[str, Any]:
        """Mark a bot for restart and release any current job."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                bot = await uow.bots.find_by_id(bot_id)
                if not bot:
                    raise NotFoundError("Bot", bot_id)
                
                # Mark bot as down
                await uow.execute_command("""
                    UPDATE bots 
                    SET status = 'down',
                        health_status = 'normal',
                        stuck_job_id = NULL
                    WHERE id = $1
                """, bot_id)
                
                # Release current job if any
                if bot.get('current_job_id'):
                    await uow.jobs.release_to_pending(bot['current_job_id'])
                
                logger.info(f"Manually restarted bot: {bot_id}")
                
                return {
                    "status": "restarted",
                    "bot_id": bot_id,
                    "released_job_id": bot.get('current_job_id'),
                    "message": f"Bot {bot_id} has been marked for restart"
                }
                
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to restart bot {bot_id}: {e}")
            raise ValidationError(f"Failed to restart bot: {str(e)}")
    
    async def cleanup_dead_bots(self) -> Dict[str, Any]:
        """Remove bots that have been down for more than 10 minutes."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                count = await uow.bots.cleanup_dead_bots(minutes=10)
                
                logger.info("Cleaned up dead bots", count=count)
                return {"cleaned_up": count, "status": "success"}
                
        except Exception as e:
            logger.error("Failed to cleanup dead bots", error=str(e))
            raise ValidationError(f"Failed to cleanup bots: {str(e)}")
    
    async def reset_all_bot_states(self) -> Dict[str, Any]:
        """Reset all bots to idle state and handle their orphaned jobs."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                # Get all bots with current jobs
                query = """
                    SELECT id, current_job_id FROM bots 
                    WHERE current_job_id IS NOT NULL AND deleted_at IS NULL
                """
                bots_with_jobs = await uow.execute_query(query)
                
                reset_count = 0
                for bot in bots_with_jobs:
                    bot_id = bot['id']
                    job_id = bot['current_job_id']
                    
                    # Check job status
                    job = await uow.jobs.find_by_id(job_id)
                    
                    if job and job['status'] in ['claimed', 'processing']:
                        # Return job to pending
                        await uow.jobs.release_to_pending(job_id)
                        logger.info("Reset job to pending", job_id=job_id)
                    
                    # Clear bot's current job
                    await uow.bots.set_current_job(bot_id, None, 'idle')
                    
                    reset_count += 1
                    logger.info("Reset bot to idle", bot_id=bot_id)
                
                return {"reset_bots": reset_count, "status": "success"}
                
        except Exception as e:
            logger.error("Failed to reset bot states", error=str(e))
            raise ValidationError(f"Failed to reset bot states: {str(e)}")
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get bot system metrics."""
        try:
            async with create_unit_of_work(self.db.pool) as uow:
                return await uow.bots.get_metrics()
                
        except Exception as e:
            logger.error("Failed to get bot metrics", error=str(e))
            raise ValidationError(f"Failed to get metrics: {str(e)}")