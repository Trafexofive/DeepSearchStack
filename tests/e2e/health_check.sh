#!/bin/bash
# ======================================================================================
# DeepSearchStack - Health Check Script for Docker Compose Services
# 
# This script performs comprehensive health checks on all services in the stack
# and provides detailed status reports.
# ======================================================================================

set -e

# Load environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

if [ -f "$ROOT_DIR/.env" ]; then
    export $(grep -v '^#' "$ROOT_DIR/.env" | xargs)
fi

COMPOSE_FILE="$ROOT_DIR/infra/docker-compose.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

check_service_health() {
    local service=$1
    local port=$2
    local health_endpoint=$3
    
    echo -e "${BLUE}Checking $service...${NC}"
    
    # Check if container is running
    if docker compose -f "$COMPOSE_FILE" ps "$service" | grep -q "Up"; then
        echo -e "  Status: ${GREEN}RUNNING${NC}"
        
        # Check health endpoint if provided
        if [ -n "$health_endpoint" ]; then
            if curl -sf "$health_endpoint" > /dev/null 2>&1; then
                echo -e "  Health: ${GREEN}HEALTHY${NC}"
                return 0
            else
                echo -e "  Health: ${RED}UNHEALTHY${NC}"
                return 1
            fi
        else
            return 0
        fi
    else
        echo -e "  Status: ${RED}NOT RUNNING${NC}"
        return 1
    fi
}

echo -e "${YELLOW}========================================================="
echo -e "     DeepSearchStack Service Health Report"
echo -e "=========================================================${NC}"

echo ""
echo -e "${YELLOW}Core Infrastructure:${NC}"
check_service_health "postgres" "5432" "http://localhost:5432"  # Note: PostgreSQL needs special check
check_service_health "redis" "6379" "http://localhost:6379/ping"  # Note: Redis needs special check

echo ""
echo -e "${YELLOW}AI Services:${NC}"
check_service_health "ollama-orchestrator" "11434" "http://localhost:11434/admin/instances"
check_service_health "llm-gateway" "8080" "http://localhost:8080/health"

echo ""
echo -e "${YELLOW}Core Logic:${NC}"
check_service_health "search-gateway" "8002" "http://localhost:8002/health"
check_service_health "deepsearch" "8001" "http://localhost:8001/health"

echo ""
echo -e "${YELLOW}User Interface & Proxy:${NC}"
check_service_health "reverse-proxy" "8090" "http://localhost:8090"
check_service_health "frontend" "3002" "http://localhost:3002"

echo ""
echo -e "${YELLOW}Utility & Data Services:${NC}"
check_service_health "vector-store" "8004" "http://localhost:8004/health"
check_service_health "crawler" "8003" "http://localhost:8003/health"

echo ""
echo -e "${YELLOW}Search Backends:${NC}"
check_service_health "yacy" "8090" "http://localhost:8090/api/status.json"
check_service_health "whoogle" "5000" ""  # No specific health check
check_service_health "searxng" "8080" ""  # No specific health check

echo ""
echo -e "${YELLOW}========================================================="
echo -e "     Health Check Complete"
echo -e "=========================================================${NC}"

# Check overall status
total_services=$(docker compose -f "$COMPOSE_FILE" ps | grep -c "Up" || echo 0)
total_containers=$(docker compose -f "$COMPOSE_FILE" ps | grep -v "NAME" | wc -l)

echo -e "Running Services: ${GREEN}${total_services}${NC} / ${total_containers}"