#!/bin/bash
# Monitor cleanup operations

set -e

# Configuration
MAIN_SERVER_URL="${MAIN_SERVER_URL:-http://localhost:3001}"
ADMIN_TOKEN="${ADMIN_TOKEN:-admin-secret-token}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Cleanup Service Monitor ===${NC}"
echo

# Function to check cleanup status
check_cleanup_status() {
    echo -e "${YELLOW}Checking cleanup service status...${NC}"
    curl -s "${MAIN_SERVER_URL}/admin/cleanup/status" | jq .
    echo
}

# Function to trigger dry-run cleanup
trigger_dry_run() {
    echo -e "${YELLOW}Triggering dry-run cleanup...${NC}"
    curl -s -X POST "${MAIN_SERVER_URL}/admin/cleanup?dry_run=true" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" | jq .
    echo
}

# Function to trigger actual cleanup
trigger_cleanup() {
    echo -e "${RED}WARNING: This will perform actual cleanup!${NC}"
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" = "yes" ]; then
        echo -e "${YELLOW}Triggering cleanup...${NC}"
        curl -s -X POST "${MAIN_SERVER_URL}/admin/cleanup?dry_run=false" \
            -H "Authorization: Bearer ${ADMIN_TOKEN}" | jq .
    else
        echo "Cleanup cancelled"
    fi
    echo
}

# Function to check orphaned resources
check_orphaned_resources() {
    echo -e "${YELLOW}Checking for orphaned resources...${NC}"
    
    # Check stopped containers
    echo "Stopped bot containers:"
    docker ps -a --filter "name=bot-" --filter "status=exited" --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}"
    echo
    
    # Check database for deleted bots
    echo "Deleted bot records in database:"
    docker exec distributed-system-test-postgres-1 psql -U ds_user -d distributed_system -c \
        "SELECT id, deleted_at, EXTRACT(EPOCH FROM (NOW() - deleted_at))/86400 as days_ago 
         FROM bots 
         WHERE deleted_at IS NOT NULL 
         ORDER BY deleted_at DESC 
         LIMIT 10;"
    echo
}

# Menu
while true; do
    echo -e "${GREEN}Choose an option:${NC}"
    echo "1) Check cleanup service status"
    echo "2) Check orphaned resources"
    echo "3) Trigger dry-run cleanup"
    echo "4) Trigger actual cleanup"
    echo "5) Exit"
    
    read -p "Enter choice: " choice
    echo
    
    case $choice in
        1) check_cleanup_status ;;
        2) check_orphaned_resources ;;
        3) trigger_dry_run ;;
        4) trigger_cleanup ;;
        5) exit 0 ;;
        *) echo -e "${RED}Invalid choice${NC}" ;;
    esac
    
    echo
    echo "Press Enter to continue..."
    read
    clear
done