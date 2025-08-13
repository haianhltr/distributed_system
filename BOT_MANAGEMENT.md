# Bot Management MVP Guide

## Quick Start

### View Current Bots
```bash
# See all bots and their status
curl http://localhost:3001/bots | jq

# Or use the dashboard
open http://localhost:3002/
```

### Scale Up (Add More Bots)
```bash
# Add 3 more bots
cd scripts
chmod +x manage-bots.sh
./manage-bots.sh scale-up 3
```

### Scale Down (Remove Bots)
```bash
# Remove 2 bots
./manage-bots.sh scale-down 2
```

### Check Bot Performance
```bash
# Get stats for a specific bot
curl "http://localhost:3001/bots/bot-docker-1/stats" | jq

# Example response:
{
  "bot_id": "bot-docker-1",
  "total_jobs": 15,
  "avg_duration_ms": 285000,
  "succeeded": 14,
  "failed": 1,
  "success_rate": 93.3
}
```

### Cleanup Dead Bots
```bash
# Remove bots that haven't sent heartbeat in 10+ minutes
curl -X POST http://localhost:3001/bots/cleanup \
  -H "Authorization: Bearer admin-secret-token"
```

### Monitor System Health
```bash
# Get overall system metrics
curl http://localhost:3001/metrics/summary | jq

# View in dashboard
open http://localhost:3002/
```

## Production Recommendations

### 1. **Automated Scaling**
Set up a cron job to scale based on queue length:

```bash
# check-and-scale.sh
#!/bin/bash
QUEUE_SIZE=$(curl -s http://localhost:3001/jobs?status=pending | jq length)
ACTIVE_BOTS=$(curl -s http://localhost:3001/bots | jq '[.[] | select(.computed_status != "down")] | length')

if [ $QUEUE_SIZE -gt $((ACTIVE_BOTS * 3)) ]; then
    echo "Queue too long, scaling up..."
    ./manage-bots.sh scale-up 2
fi
```

### 2. **Health Monitoring**
Run periodic health checks:

```bash
# Add to crontab: */5 * * * *
curl -X POST http://localhost:3001/bots/cleanup \
  -H "Authorization: Bearer admin-secret-token" > /dev/null 2>&1
```

### 3. **Performance Alerts**
Monitor bot performance:

```bash
# Check for underperforming bots
for bot in $(curl -s http://localhost:3001/bots | jq -r '.[].id'); do
    stats=$(curl -s "http://localhost:3001/bots/$bot/stats")
    success_rate=$(echo $stats | jq -r '.success_rate')
    if (( $(echo "$success_rate < 80" | bc -l) )); then
        echo "WARNING: Bot $bot has low success rate: $success_rate%"
    fi
done
```

## Next Steps for Production

1. **Add Kubernetes support** for true auto-scaling
2. **Implement bot configuration management**
3. **Add bot grouping** for different job types
4. **Set up proper monitoring** (CloudWatch, Datadog, etc.)
5. **Add circuit breakers** for failing bots