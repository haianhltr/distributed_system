-- Migration 001: Add multi-operation support
-- Adds operation field to jobs and assigned_operation to bots

BEGIN;

-- Add operation field to jobs table (default 'sum' for backward compatibility)
ALTER TABLE jobs ADD COLUMN operation TEXT NOT NULL DEFAULT 'sum';

-- Add assigned_operation field to bots table (nullable for dynamic assignment)
ALTER TABLE bots ADD COLUMN assigned_operation TEXT;

-- Add index for efficient operation-based job claiming
CREATE INDEX idx_jobs_operation_status_created 
ON jobs(operation, status, created_at) 
WHERE status = 'pending';

-- Add index for bot operation queries
CREATE INDEX idx_bots_assigned_operation 
ON bots(assigned_operation) 
WHERE assigned_operation IS NOT NULL;

-- Update existing jobs to have 'sum' operation for backward compatibility
UPDATE jobs SET operation = 'sum' WHERE operation IS NULL;

-- Add check constraint for valid operations (will be updated by plugin loader)
ALTER TABLE jobs ADD CONSTRAINT check_jobs_operation 
CHECK (operation IN ('sum', 'subtract', 'multiply', 'divide'));

-- Add comment for future reference
COMMENT ON COLUMN jobs.operation IS 'Operation type for this job - loaded dynamically from operations/ plugins';
COMMENT ON COLUMN bots.assigned_operation IS 'Assigned operation for bot - NULL means bot can claim any operation and will be assigned dynamically';

COMMIT;