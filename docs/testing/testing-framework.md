# Chaos Engineering and Load Testing Suite

This testing suite provides comprehensive chaos engineering and load testing capabilities for the distributed job processing system.

## Features

### Chaos Engineering (`chaos_monkey.py`)
- **Database Delays**: Inject latency into database operations
- **Connection Killing**: Terminate random database connections to test recovery
- **Network Delays**: Simulate network partitions and latency
- **State Corruption**: Inject inconsistent bot states to test cleanup
- **Continuous Monitoring**: Track system health during chaos experiments

### Load Testing (`load_tester.py`)
- **Race Condition Testing**: Test multiple bots claiming the same job simultaneously
- **Stress Testing**: High-concurrency job claiming with 100+ concurrent bots
- **Database Stress Testing**: Job claiming under database load
- **Consistency Verification**: Detect race conditions and data inconsistencies
- **Performance Metrics**: Response times, throughput, success rates

### Test Runner (`test_runner.py`)
- **Unified Interface**: Run all tests through a single command
- **System Health Checks**: Comprehensive consistency and health monitoring
- **Result Reporting**: Detailed JSON reports with recommendations
- **Configurable**: Support for different environments and configurations

## Quick Start

### 1. Install Dependencies
```bash
cd testing
pip install -r requirements.txt
```

### 2. Run Tests

**Quick Race Condition Test:**
```bash
python test_runner.py --test-type race
```

**Full Load Testing Suite:**
```bash
python test_runner.py --test-type load --save-results
```

**Chaos Engineering Tests:**
```bash
python test_runner.py --test-type chaos --save-results
```

**System Health Check:**
```bash
python test_runner.py --test-type health
```

**Run Everything:**
```bash
python test_runner.py --test-type all --save-results
```

### 3. Configuration

```bash
python test_runner.py \
  --database-url "postgresql://ds_user:ds_password@localhost:5432/distributed_system" \
  --main-server-url "http://localhost:3001" \
  --admin-token "admin-secret-token" \
  --test-type all \
  --save-results
```

## Test Scenarios

### Race Condition Detection
Tests specifically designed to detect the race condition we found:

1. **Simultaneous Claims**: 50 bots try to claim the same job at exactly the same time
2. **High Concurrency**: 100 bots continuously claim jobs for 60 seconds
3. **Database Stress**: Job claiming while database is under heavy load

### Chaos Engineering Scenarios

1. **Database Resilience**:
   - Inject 1-5 second delays into database queries
   - Kill random database connections
   - Measure recovery time and system stability

2. **Network Partition**:
   - Inject 2-second network delays
   - Test service communication under network stress
   - Verify graceful degradation

3. **State Corruption**:
   - Inject inconsistent bot-job assignments
   - Test cleanup service effectiveness
   - Verify data consistency recovery

### Load Testing Scenarios

1. **Light Load**: 10 bots for 30 seconds
2. **Medium Load**: 25 bots for 60 seconds  
3. **Heavy Load**: 50 bots for 60 seconds
4. **Extreme Load**: 100 bots for 60 seconds

## Expected Results

### Healthy System
- **No race conditions detected**
- **Response times < 100ms**
- **Success rate > 95%**
- **No consistency violations**
- **Recovery time < 30 seconds**

### Common Issues Detected
- **Duplicate job assignments** (race condition)
- **Orphaned bot states** (cleanup failure)
- **Stuck pending jobs** (blocking issues)
- **High response times** (performance issues)
- **Low success rates** (error handling issues)

## Interpreting Results

### Race Condition Detection
```json
{
  "race_condition_detected": true,
  "successful_requests": 3,
  "total_requests": 50,
  "consistency_violations": [
    "Job abc123 assigned to 3 bots"
  ]
}
```
**Action**: Fix job claiming logic with proper database locking

### Performance Issues
```json
{
  "requests_per_second": 2.5,
  "average_response_time_ms": 2000,
  "p95_response_time_ms": 5000
}
```
**Action**: Optimize database queries, add connection pooling

### Consistency Violations
```json
{
  "orphaned_bots": [
    {"id": "bot-123", "current_job_id": "job-456"}
  ],
  "duplicate_assignments": [
    {"current_job_id": "job-789", "bot_ids": ["bot-1", "bot-2"]}
  ]
}
```
**Action**: Implement database constraints, improve cleanup logic

## Best Practices Validated

✅ **Use `FOR UPDATE SKIP LOCKED`** for atomic job claiming  
✅ **Implement proper database constraints** to prevent inconsistent states  
✅ **Add circuit breakers** with exponential backoff  
✅ **Monitor system health** continuously  
✅ **Test under load** regularly in staging environment  

## Production Recommendations

Based on test results, the system should implement:

1. **Database-level job claiming** with `FOR UPDATE SKIP LOCKED`
2. **Consistency constraints** to prevent orphaned states  
3. **Connection pooling** with health checks
4. **Circuit breakers** for graceful failure handling
5. **Monitoring** for race conditions and consistency violations
6. **Automated cleanup** for inconsistent states

## Troubleshooting

### Test Failures
- Ensure main server is running on port 3001
- Verify database is accessible and has correct schema
- Check admin token is correct
- Ensure no other load tests are running simultaneously

### Performance Issues
- Tests create significant database load
- Run tests in isolated environment
- Monitor system resources during testing
- Consider reducing bot counts for slower systems

### False Positives
- Network delays can cause timeouts that look like race conditions
- Database connection limits can cause failures
- Ensure adequate system resources for testing load