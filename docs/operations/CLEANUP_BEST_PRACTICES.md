# Cleanup Best Practices for Distributed Systems

## Overview

This document outlines best practices for managing resource cleanup in the distributed job processing system, addressing:
- Orphaned Docker containers
- Database record retention
- Automated cleanup scheduling
- Monitoring and alerting

## Architecture

### 1. Cleanup Service (`main_server/cleanup_service.py`)

The cleanup service implements a **scheduled background task** pattern with:
- Configurable retention policies
- Dry-run support for safety
- Comprehensive logging
- Error recovery with retry logic

```python
# Key configuration
BOT_RETENTION_DAYS=7          # Keep deleted bot records for 7 days
CLEANUP_INTERVAL_HOURS=6      # Run cleanup every 6 hours
CONTAINER_CLEANUP_ENABLED=true # Enable Docker container cleanup
CLEANUP_DRY_RUN=false         # Set to true for testing
```

### 2. Database Cleanup Strategy

**Soft Delete Pattern**: Bots are marked with `deleted_at` timestamp rather than immediately removed.

Benefits:
- Audit trail for debugging
- Recovery possible if needed
- Referential integrity maintained

Cleanup rules:
- Deleted bot records older than `BOT_RETENTION_DAYS` are purged
- Orphaned results (referencing non-existent bots) are cleaned
- Uses database transactions for consistency

### 3. Container Cleanup Strategy

**Stateless Container Management**: Containers are ephemeral and can be safely removed when stopped.

Process:
1. Query active bots from database
2. List all bot containers (running and stopped)
3. Remove stopped containers not in active bot list
4. Log all cleanup actions

### 4. Monitoring and Alerting

**Multi-level Monitoring**:
- Service health endpoint: `/admin/cleanup/status`
- Manual trigger endpoint: `/admin/cleanup`
- Shell script for operators: `scripts/monitor-cleanup.sh`

## Implementation Details

### Scheduled Cleanup

```python
# Runs on startup after 1-minute delay
await cleanup_scheduler.start()

# Periodic execution every CLEANUP_INTERVAL_HOURS
while self._running:
    await self.run_cleanup()
    await asyncio.sleep(interval)
```

### Manual Cleanup

```bash
# Dry run to preview actions
curl -X POST http://localhost:3001/admin/cleanup?dry_run=true \
  -H "Authorization: Bearer admin-secret-token"

# Actual cleanup
curl -X POST http://localhost:3001/admin/cleanup?dry_run=false \
  -H "Authorization: Bearer admin-secret-token"
```

### Monitoring Script

```bash
# Interactive monitoring tool
./scripts/monitor-cleanup.sh

# Options:
# 1) Check service status
# 2) List orphaned resources
# 3) Trigger dry-run
# 4) Perform cleanup
```

## Best Practices

### 1. **Gradual Rollout**
- Start with `CLEANUP_DRY_RUN=true` to observe behavior
- Monitor logs for several cycles
- Enable actual cleanup once confident

### 2. **Retention Tuning**
- Start conservative (e.g., 7-30 days retention)
- Adjust based on:
  - Debugging needs
  - Storage constraints
  - Compliance requirements

### 3. **Error Handling**
- Circuit breakers prevent cascading failures
- Failed cleanups retry after 5 minutes
- All errors logged with context

### 4. **Performance Considerations**
- Cleanup runs during off-peak hours
- Database operations use indexed queries
- Batch deletes to minimize lock time

### 5. **Safety Measures**
- Never delete active resources
- Verify bot state before container removal
- Transaction rollback on errors
- Comprehensive audit logging

## Operational Procedures

### Daily Operations
1. Check cleanup status via dashboard
2. Review cleanup logs for anomalies
3. Monitor resource usage trends

### Weekly Maintenance
1. Review retention metrics
2. Adjust cleanup intervals if needed
3. Verify no false-positive cleanups

### Incident Response
1. If cleanup fails repeatedly:
   - Check database connectivity
   - Verify Docker daemon health
   - Review error logs
   - Run manual cleanup with dry-run

2. If resources accumulate:
   - Temporarily reduce retention period
   - Increase cleanup frequency
   - Investigate root cause

## Environment Variables

```bash
# Cleanup configuration
BOT_RETENTION_DAYS=7              # Days to keep deleted bot records
CLEANUP_INTERVAL_HOURS=6          # Hours between cleanup runs
CONTAINER_CLEANUP_ENABLED=true    # Enable/disable container cleanup
CLEANUP_DRY_RUN=false            # Dry run mode for testing

# Existing configuration
MAIN_SERVER_URL=http://localhost:3001
ADMIN_TOKEN=admin-secret-token
DATABASE_URL=postgresql://...
```

## Metrics and KPIs

Track these metrics for cleanup effectiveness:
- Resources cleaned per run
- Cleanup execution time
- Failed cleanup attempts
- Storage space recovered
- Orphaned resource detection rate

## Future Enhancements

1. **Prometheus Metrics**
   - Export cleanup metrics
   - Create Grafana dashboards
   - Set up alerts

2. **Intelligent Scheduling**
   - Adaptive cleanup frequency
   - Load-based scheduling
   - Priority-based retention

3. **Advanced Policies**
   - Tag-based retention
   - Performance-based cleanup
   - Cost optimization rules