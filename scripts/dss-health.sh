#!/bin/bash
# DSS Health Monitor — checks all services, restarts dead ones.
# Run via cron: */5 * * * * /path/to/dss-health.sh >> /tmp/dss-health.log 2>&1

set -e
DSS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/dss-health.log"

health() {
    local svc=$1 port=$2
    if curl -sf --max-time 5 "http://localhost:${port}/health" > /dev/null 2>&1; then
        return 0
    fi
    echo "[$(date -Is)] ${svc}:${port} DOWN — restarting" >> "$LOG"
    cd "$DSS_DIR" && make up STACK=full >> "$LOG" 2>&1
    echo "[$(date -Is)] ${svc} restarted" >> "$LOG"
    return 1
}

health "knowledge-warehouse" 8009
health "crawler" 8000
health "web-api" 8014
health "search-gateway" 8002
health "search-agent" 8013
# health "postgres" 5432  # critical — don't auto-restart
# health "redis" 6379
health "proxy-rotator" 8030

echo "[$(date -Is)] health check complete" >> "$LOG"
