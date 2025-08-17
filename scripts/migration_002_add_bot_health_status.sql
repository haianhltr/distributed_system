-- Migration 002: Fix bot health status tracking for job release
-- Date: 2025-08-17
-- Purpose: Fix job release bug by ensuring health_status includes 'unhealthy' value

-- First, drop the existing constraint if it exists
DO $$
BEGIN
    -- Check if the constraint exists with the old values
    IF EXISTS (
        SELECT 1 
        FROM information_schema.constraint_column_usage 
        WHERE table_name = 'bots' 
        AND constraint_name = 'bots_health_status_check'
    ) THEN
        ALTER TABLE bots DROP CONSTRAINT bots_health_status_check;
    END IF;
END
$$;

-- Add the updated constraint with all three values
ALTER TABLE bots ADD CONSTRAINT bots_health_status_check 
    CHECK (health_status IN ('normal', 'potentially_stuck', 'unhealthy'));

-- Create missing indexes
CREATE INDEX IF NOT EXISTS idx_bots_stuck_job ON bots(stuck_job_id) WHERE stuck_job_id IS NOT NULL;

-- Create migration log table if it doesn't exist
CREATE TABLE IF NOT EXISTS migration_log (
    id SERIAL PRIMARY KEY,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    applied_by TEXT DEFAULT current_user
);

-- Record this migration
INSERT INTO migration_log (migration_name) 
VALUES ('002_fix_bot_health_status')
ON CONFLICT (migration_name) DO NOTHING;

-- Verify the schema is correct
DO $$
DECLARE
    col_count INTEGER;
BEGIN
    -- Check that all required columns exist
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns 
    WHERE table_name = 'bots' 
    AND column_name IN ('health_status', 'stuck_job_id', 'health_checked_at');
    
    IF col_count < 3 THEN
        RAISE EXCEPTION 'Not all required columns exist in bots table. Found % of 3', col_count;
    END IF;
    
    RAISE NOTICE 'Migration 002 completed successfully. Health status constraint updated.';
END
$$;