#!/bin/bash
# DSS Health Monitor — checks all services, restarts dead ones.
# Run via cron: */5 * * * * /path/to/dss-health.sh >> /tmp/dss-health.log 2>&1

set -e
DSS_DIR="$HOME/repos/substrate/services/DeepSearchStack"
LOG="/tmp/dss-health.log"

health() {
    local svc=$1 port=$2
    if curl -sf --max-time 5 "http://localhost:${port}/health" > /dev/null 2>&1; then
        return 0
    fi
    echo "[$(date -Is)] ${svc}:${port} DOWN — restarting" >> "$LOG"
    cd "$HOME/repos/substrate" && make recreate "dss/${svc}" >> "$LOG" 2>&1
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
health "inference_gateway" 8005

echo "[$(date -Is)] health check complete" >> "$LOG"
