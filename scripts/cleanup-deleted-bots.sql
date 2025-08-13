-- Script to permanently remove soft-deleted bot records
-- WARNING: This will permanently delete data and cannot be undone!

-- Show what will be deleted
SELECT id, status, deleted_at, last_heartbeat_at 
FROM bots 
WHERE deleted_at IS NOT NULL
ORDER BY deleted_at DESC;

-- Count records to be deleted
SELECT COUNT(*) as "Records to delete" 
FROM bots 
WHERE deleted_at IS NOT NULL;

-- Uncomment below to actually delete the records
-- DELETE FROM bots WHERE deleted_at IS NOT NULL;

-- Alternative: Delete bots that have been soft-deleted for more than 7 days
-- DELETE FROM bots WHERE deleted_at IS NOT NULL AND deleted_at < NOW() - INTERVAL '7 days';