#!/bin/bash
# Simple bot management script for MVP

set -e

ACTION=$1
COUNT=${2:-1}

case $ACTION in
  "scale-up")
    echo "Scaling up $COUNT bots..."
    for i in $(seq 1 $COUNT); do
      BOT_ID="bot-manual-$(date +%s)-$i"
      docker run -d \
        --network distributed-system \
        --name $BOT_ID \
        -e BOT_ID=$BOT_ID \
        -e MAIN_SERVER_URL=http://main-server:3001 \
        -e HEARTBEAT_INTERVAL_MS=30000 \
        -e PROCESSING_DURATION_MS=300000 \
        -e FAILURE_RATE=0.15 \
        distributed-system-test-bot:latest
      echo "Started bot: $BOT_ID"
    done
    ;;
    
  "scale-down")
    echo "Scaling down $COUNT bots..."
    BOTS=$(docker ps --filter "name=bot-manual-" --format "{{.Names}}" | head -n $COUNT)
    for BOT in $BOTS; do
      docker stop $BOT
      docker rm $BOT
      echo "Stopped bot: $BOT"
    done
    ;;
    
  "cleanup")
    echo "Cleaning up dead bots..."
    curl -X POST http://localhost:3001/bots/cleanup \
      -H "Authorization: Bearer admin-secret-token"
    ;;
    
  "status")
    echo "Bot Status:"
    curl -s http://localhost:3001/bots | jq -r '.[] | "\(.id): \(.computed_status) (last heartbeat: \(.last_heartbeat_at))"'
    ;;
    
  *)
    echo "Usage: $0 {scale-up|scale-down|cleanup|status} [count]"
    echo "  scale-up N   - Start N new bots"
    echo "  scale-down N - Stop N running bots"
    echo "  cleanup      - Remove dead bots from database"
    echo "  status       - Show all bot statuses"
    exit 1
    ;;
esac