#!/bin/bash
# DSS Overnight Monitor
watch -n 30 '
echo "=== DSS OVERNIGHT MONITOR ==="
date
echo ""
echo "--- Warehouse ---"
curl -s --max-time 5 localhost:8009/stats | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"  {d[\"total_entries\"]} entries, {d[\"db_size_mb\"]}MB\")"
echo ""
echo "--- Jobs ---"
ps aux | grep "dss-overnight" | grep -v grep | awk "{print \"  \" \$11,\$12,\$13,\"PID:\"\$2}"
echo ""
echo "--- Awesome-list ---"
tail -3 /tmp/dss-overnight.log 2>/dev/null
echo ""
echo "--- Books ---"
tail -3 /tmp/dss-overnight-books.log 2>/dev/null
echo ""
echo "--- Crawler ---"
docker logs dss-crawler --tail 1 2>&1 | tail -1
'
