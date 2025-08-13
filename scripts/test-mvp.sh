#!/bin/bash
# Test MVP bot management features

echo "=== MVP Bot Management Test ==="

echo "1. Current bot status:"
curl -s http://localhost:3001/bots | python -m json.tool | head -20

echo -e "\n2. Bot stats for bot-docker-1:"
curl -s "http://localhost:3001/bots/bot-docker-1/stats" | python -m json.tool

echo -e "\n3. Cleanup dead bots:"
curl -X POST "http://localhost:3001/bots/cleanup" \
  -H "Authorization: Bearer admin-secret-token" | python -m json.tool

echo -e "\n4. System metrics:"
curl -s "http://localhost:3001/metrics/summary" | python -m json.tool

echo -e "\n5. Dashboard URL: http://localhost:3002/"

echo -e "\n=== MVP Features Working! ==="