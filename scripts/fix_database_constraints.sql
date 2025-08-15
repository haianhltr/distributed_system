-- Database Fixes for Race Condition Prevention
-- Apply these changes to prevent job claiming race conditions

-- ===================================================================
-- PHASE 1: Add Critical Business Rule Constraints (IMMEDIATE PROTECTION)
-- ===================================================================

-- 1. Add constraint to prevent inconsistent job states
-- This ensures pending jobs cannot have claimed_by set, and claimed jobs must have claimed_by
ALTER TABLE jobs ADD CONSTRAINT job_state_consistency
CHECK (
  (status = 'pending' AND claimed_by IS NULL) OR
  (status IN ('claimed', 'processing', 'succeeded', 'failed') AND claimed_by IS NOT NULL)
);

-- 2. Add version column for optimistic locking
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;

-- 3. Add constraint to prevent multiple bots from having the same job
-- First, let's see if this constraint exists
-- DROP CONSTRAINT IF EXISTS unique_bot_current_job;
ALTER TABLE bots ADD CONSTRAINT unique_bot_current_job 
UNIQUE (current_job_id) 
WHERE current_job_id IS NOT NULL;

-- ===================================================================
-- PHASE 2: Add Foreign Key Constraints (DATA INTEGRITY)
-- ===================================================================

-- 4. Add foreign key constraint from bots to jobs
-- This ensures bots can only reference jobs that exist
ALTER TABLE bots ADD CONSTRAINT fk_current_job 
FOREIGN KEY (current_job_id) REFERENCES jobs(id) 
ON DELETE SET NULL;

-- 5. Add constraint for valid job status values
ALTER TABLE jobs ADD CONSTRAINT valid_job_status 
CHECK (status IN ('pending', 'claimed', 'processing', 'succeeded', 'failed'));

-- 6. Add constraint for valid bot status values  
ALTER TABLE bots ADD CONSTRAINT valid_bot_status 
CHECK (status IN ('idle', 'busy', 'down'));

-- ===================================================================
-- PHASE 3: Performance Indexes (OPTIMIZATION)
-- ===================================================================

-- 7. Add partial index for pending jobs (performance optimization)
CREATE INDEX IF NOT EXISTS idx_jobs_pending_skip_locked 
ON jobs(created_at) 
WHERE status = 'pending';

-- 8. Add index for job claiming by bot
CREATE INDEX IF NOT EXISTS idx_jobs_claimed_by 
ON jobs(claimed_by) 
WHERE claimed_by IS NOT NULL;

-- ===================================================================
-- PHASE 4: Cleanup Any Existing Inconsistent Data
-- ===================================================================

-- 9. Fix any existing inconsistent states before constraints are enforced
-- Clear bots that have non-existent jobs
UPDATE bots 
SET current_job_id = NULL 
WHERE current_job_id IS NOT NULL 
AND current_job_id NOT IN (SELECT id FROM jobs);

-- 10. Clear jobs that are pending but have claimed_by set
UPDATE jobs 
SET claimed_by = NULL 
WHERE status = 'pending' 
AND claimed_by IS NOT NULL;

-- 11. Fix jobs that are claimed but don't have claimed_by set
UPDATE jobs 
SET status = 'pending' 
WHERE status IN ('claimed', 'processing') 
AND claimed_by IS NULL;

-- ===================================================================
-- VERIFICATION QUERIES
-- ===================================================================

-- Check for remaining inconsistencies (should return 0 rows for each)
SELECT 'Pending jobs with claimed_by' as issue, COUNT(*) as count
FROM jobs 
WHERE status = 'pending' AND claimed_by IS NOT NULL
UNION ALL
SELECT 'Claimed jobs without claimed_by' as issue, COUNT(*) as count
FROM jobs 
WHERE status IN ('claimed', 'processing') AND claimed_by IS NULL
UNION ALL
SELECT 'Bots with non-existent jobs' as issue, COUNT(*) as count
FROM bots b
LEFT JOIN jobs j ON b.current_job_id = j.id
WHERE b.current_job_id IS NOT NULL AND j.id IS NULL
UNION ALL
SELECT 'Duplicate job assignments' as issue, COUNT(*) - COUNT(DISTINCT current_job_id) as count
FROM bots 
WHERE current_job_id IS NOT NULL;

-- Show current job distribution
SELECT 
  j.status,
  COUNT(*) as job_count,
  COUNT(DISTINCT j.claimed_by) as unique_bots
FROM jobs j
GROUP BY j.status
ORDER BY j.status;