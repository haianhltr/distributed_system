import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
import os

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None
    
    async def initialize(self):
        """Initialize database connection pool and schema"""
        try:
            # Create connection pool
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            
            # Create schema
            async with self.get_connection() as conn:
                schema = """
                -- Database schema for distributed job processing system
                
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    a INTEGER NOT NULL,
                    b INTEGER NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'sum',
                    status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'processing', 'succeeded', 'failed')),
                    claimed_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_at TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    attempts INTEGER DEFAULT 0,
                    error TEXT,
                    version INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS bots (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ('idle', 'busy', 'down')),
                    current_job_id TEXT,
                    assigned_operation TEXT,
                    last_heartbeat_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP,
                    health_status TEXT DEFAULT 'normal' CHECK (health_status IN ('normal', 'potentially_stuck', 'unhealthy')),
                    stuck_job_id TEXT,
                    health_checked_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    a INTEGER NOT NULL,
                    b INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    result INTEGER NOT NULL,
                    processed_by TEXT NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_ms INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
                    error TEXT
                );

                -- Auth tables for token-based authentication
                CREATE TABLE IF NOT EXISTS auth_bots (
                    bot_key TEXT PRIMARY KEY,
                    bootstrap_secret_hash BYTEA NOT NULL,
                    secret_version INTEGER NOT NULL DEFAULT 1,
                    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS bot_auth_guard (
                    bot_key TEXT PRIMARY KEY REFERENCES auth_bots(bot_key),
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    last_failed_at TIMESTAMPTZ,
                    locked_until TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS revoked_jti (
                    jti UUID PRIMARY KEY,
                    bot_key TEXT NOT NULL REFERENCES auth_bots(bot_key),
                    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                );

                -- Indexes for performance
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_claimed_by ON jobs(claimed_by);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_operation_status_created ON jobs(operation, status, created_at) WHERE status = 'pending';
                CREATE INDEX IF NOT EXISTS idx_jobs_processing_duration ON jobs(started_at) WHERE status = 'processing';
                CREATE INDEX IF NOT EXISTS idx_bots_status ON bots(status);
                CREATE INDEX IF NOT EXISTS idx_bots_heartbeat ON bots(last_heartbeat_at);
                CREATE INDEX IF NOT EXISTS idx_bots_assigned_operation ON bots(assigned_operation) WHERE assigned_operation IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_bots_health_status ON bots(health_status);
                CREATE INDEX IF NOT EXISTS idx_results_job_id ON results(job_id);
                CREATE INDEX IF NOT EXISTS idx_results_processed_at ON results(processed_at);
                CREATE INDEX IF NOT EXISTS idx_results_operation ON results(operation);

                -- Auth table indexes
                CREATE INDEX IF NOT EXISTS idx_auth_bots_enabled ON auth_bots(is_enabled);
                CREATE INDEX IF NOT EXISTS idx_bot_auth_guard_locked_until ON bot_auth_guard(locked_until);
                CREATE INDEX IF NOT EXISTS idx_revoked_jti_expires_at ON revoked_jti(expires_at);
                CREATE INDEX IF NOT EXISTS idx_revoked_jti_bot_key ON revoked_jti(bot_key);

                -- Ensure atomic job claiming
                CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_current_job ON bots(current_job_id) WHERE current_job_id IS NOT NULL;
                """
                
                await conn.execute(schema)
                
            logger.info("PostgreSQL database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a database connection from pool"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        
        async with self.pool.acquire() as conn:
            yield conn
    
    async def close(self):
        """Close the database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")