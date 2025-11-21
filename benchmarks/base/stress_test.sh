#!/bin/bash
# ======================================================================================
# DeepSearchStack - Base Benchmarks Runner
# 
# Real-world performance tests for core functionality:
# - Concurrent crawling of various web sources
# - Search aggregation performance
# - LLM response quality and speed
# 
# These benchmarks simulate actual usage patterns, not synthetic loads.
# ======================================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPORT_DIR="reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$REPORT_DIR/benchmark_${TIMESTAMP}.log"
RESULT_FILE="$REPORT_DIR/results_${TIMESTAMP}.json"

# Create reports directory
mkdir -p "$REPORT_DIR"

# Test configuration
NUM_CONCURRENT_REQUESTS=10
NUM_TOTAL_REQUESTS=50
WARMUP_REQUESTS=5

echo -e "${CYAN}🚀 Starting DeepSearchStack Base Benchmarks${NC}"
echo -e "${BLUE}Timestamp:${NC} $TIMESTAMP"
echo -e "${BLUE}Log file:${NC} $LOG_FILE"
echo ""

# Function to log and echo
log_echo() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

# Function to check if a service is available
check_service() {
    local service_name=$1
    local url=$2
    
    if curl -sf "$url" > /dev/null 2>&1; then
        log_echo "${GREEN}✓${NC} $service_name is available"
        return 0
    else
        log_echo "${RED}✗${NC} $service_name is NOT available at $url"
        return 1
    fi
}

# Function to format time
format_time() {
    local time_in_seconds=$1
    printf "%.3fs" "$time_in_seconds"
}

# Function to format rate
format_rate() {
    local count=$1
    local time_in_seconds=$2
    local rate=$(echo "$count $time_in_seconds" | awk '{printf "%.2f", $1/$2}')
    echo "$rate RPS"
}

# Function to run crawler benchmark
run_crawler_benchmark() {
    log_echo "${YELLOW}🔍 Starting Crawler Benchmark...${NC}"
    
    local start_time=$(date +%s.%N)
    local success_count=0
    local error_count=0
    local total_time=0
    local response_times=()
    
    # URLs that are generally available for benchmarking
    local test_urls=(
        "https://example.com"
        "https://httpbin.org/html"
        "https://httpbin.org/json"
        "https://jsonplaceholder.typicode.com/posts/1"
        "https://quotes.toscrape.com/"
        "https://httpbin.org/xml"
        "https://example.com"
        "https://jsonplaceholder.typicode.com/users/1"
        "https://quotes.toscrape.com/page/1/"
        "https://httpbin.org/robots.txt"
    )
    
    # Warmup requests
    log_echo "${BLUE}  Warming up crawler service...${NC}"
    for ((i=0; i<WARMUP_REQUESTS; i++)); do
        curl -sf -X POST http://localhost:8004/crawl \
            -H "Content-Type: application/json" \
            -d "{\"url\": \"${test_urls[$((i % ${#test_urls[@]}))]}\", \"formats\": [\"markdown\"]}" > /dev/null 2>&1 || true
        sleep 0.1
    done
    
    # Actual benchmark - run concurrently
    log_echo "${BLUE}  Running $NUM_TOTAL_REQUESTS concurrent crawl requests...${NC}"
    
    # Create a temporary file to store pids
    local pid_file=$(mktemp)
    
    # Function for individual request
    run_crawl_request() {
        local idx=$1
        local url_idx=$((idx % ${#test_urls[@]}))
        local start_req=$(date +%s.%N)
        
        local result=$(curl -s -w "\n%{time_total}" -X POST http://localhost:8004/crawl \
            -H "Content-Type: application/json" \
            -d "{\"url\": \"${test_urls[$url_idx]}\", \"formats\": [\"markdown\"]}" 2>/dev/null)
        
        local response_time=$(echo "$result" | tail -n1)
        local content=$(echo "$result" | head -n -1)
        
        if [ $? -eq 0 ] && [ -n "$content" ]; then
            echo "SUCCESS|$response_time|$idx" >> "$pid_file"
        else
            echo "ERROR|$response_time|$idx" >> "$pid_file"
        fi
    }
    
    # Launch concurrent requests
    for ((i=0; i<NUM_TOTAL_REQUESTS; i++)); do
        run_crawl_request $i &
    done
    
    # Wait for all requests to complete
    wait
    
    # Process results
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            local status=$(echo "$line" | cut -d'|' -f1)
            local resp_time=$(echo "$line" | cut -d'|' -f2)
            
            if [ "$status" = "SUCCESS" ]; then
                ((success_count++))
                response_times+=("$resp_time")
            else
                ((error_count++))
            fi
            
            # Track total time using max response time
            if (( $(echo "$resp_time > $total_time" | bc -l) )); then
                total_time=$resp_time
            fi
        fi
    done < "$pid_file"
    
    rm -f "$pid_file"
    
    local end_time=$(date +%s.%N)
    local total_duration=$(echo "$end_time - $start_time" | bc -l)
    
    # Calculate metrics
    local avg_response_time=0
    if [ ${#response_times[@]} -gt 0 ]; then
        local sum=0
        for rt in "${response_times[@]}"; do
            sum=$(echo "$sum + $rt" | bc -l)
        done
        avg_response_time=$(echo "$sum / ${#response_times[@]}" | bc -l)
    fi
    
    local min_response_time=$(printf '%s\n' "${response_times[@]}" | sort -n | head -1)
    local max_response_time=$(printf '%s\n' "${response_times[@]}" | sort -n | tail -1)
    local throughput=$(echo "$NUM_TOTAL_REQUESTS $total_duration" | awk '{printf "%.2f", $1/$2}')
    local error_rate=$(echo "$error_count $NUM_TOTAL_REQUESTS" | awk '{printf "%.2f", $1/$2*100}')
    
    log_echo "${GREEN}✅ Crawler Benchmark Results:${NC}"
    log_echo "  Requests:        $NUM_TOTAL_REQUESTS"
    log_echo "  Successful:      $success_count"
    log_echo "  Failed:          $error_count"
    log_echo "  Error Rate:      ${error_rate}%"
    log_echo "  Total Time:      $(format_time $total_duration)"
    log_echo "  Avg Response:    $(format_time $avg_response_time)"
    log_echo "  Min Response:    $(format_time $min_response_time)"
    log_echo "  Max Response:    $(format_time $max_response_time)"
    log_echo "  Throughput:      ${throughput} RPS"
    log_echo ""
    
    # Performance rating
    if (( $(echo "$throughput > 5" | bc -l) )); then
        log_echo "${GREEN}  💪 PERFORMANCE: Excellent${NC}"
    elif (( $(echo "$throughput > 2" | bc -l) )); then
        log_echo "${YELLOW}  ⚡ PERFORMANCE: Good${NC}"
    elif (( $(echo "$throughput > 0.5" | bc -l) )); then
        log_echo "${BLUE}  👌 PERFORMANCE: Acceptable${NC}"
    else
        log_echo "${RED}  🐌 PERFORMANCE: Poor${NC}"
    fi
    
    # Save detailed results
    cat << EOF > "$REPORT_DIR/crawler_results_$TIMESTAMP.json"
{
  "benchmark": "Crawler",
  "timestamp": "$TIMESTAMP",
  "requests_sent": $NUM_TOTAL_REQUESTS,
  "successful_requests": $success_count,
  "failed_requests": $error_count,
  "total_duration": $total_duration,
  "avg_response_time": $avg_response_time,
  "min_response_time": $min_response_time,
  "max_response_time": $max_response_time,
  "throughput": $throughput,
  "error_rate": $error_rate,
  "response_times": [$(printf '%s,' "${response_times[@]}" | sed 's/,$//')]
}
EOF
}

# Function to run search benchmark
run_search_benchmark() {
    log_echo "${YELLOW}🔍 Starting Search Gateway Benchmark...${NC}"
    
    local start_time=$(date +%s.%N)
    local success_count=0
    local error_count=0
    local total_time=0
    local response_times=()
    
    # Search queries for benchmarking
    local test_queries=(
        "artificial intelligence"
        "machine learning"
        "blockchain technology"
        "renewable energy"
        "climate change"
        "quantum computing"
        "space exploration"
        "genetic engineering"
        "neural networks"
        "distributed systems"
    )
    
    # Warmup requests
    log_echo "${BLUE}  Warming up search service...${NC}"
    for ((i=0; i<WARMUP_REQUESTS; i++)); do
        curl -sf -X POST http://localhost:8003/search \
            -H "Content-Type: application/json" \
            -d "{\"query\": \"${test_queries[$((i % ${#test_queries[@]}))]}\"}" > /dev/null 2>&1 || true
        sleep 0.1
    done
    
    # Actual benchmark
    log_echo "${BLUE}  Running $NUM_TOTAL_REQUESTS concurrent search requests...${NC}"
    
    local pid_file=$(mktemp)
    
    run_search_request() {
        local idx=$1
        local query_idx=$((idx % ${#test_queries[@]}))
        local start_req=$(date +%s.%N)
        
        local result=$(curl -s -w "\n%{time_total}" -X POST http://localhost:8003/search \
            -H "Content-Type: application/json" \
            -d "{\"query\": \"${test_queries[$query_idx]}\"}" 2>/dev/null)
        
        local response_time=$(echo "$result" | tail -n1)
        local content=$(echo "$result" | head -n -1)
        
        if [ $? -eq 0 ] && [ -n "$content" ]; then
            echo "SUCCESS|$response_time|$idx" >> "$pid_file"
        else
            echo "ERROR|$response_time|$idx" >> "$pid_file"
        fi
    }
    
    # Launch concurrent requests
    for ((i=0; i<NUM_TOTAL_REQUESTS; i++)); do
        run_search_request $i &
    done
    
    # Wait for all requests to complete
    wait
    
    # Process results
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            local status=$(echo "$line" | cut -d'|' -f1)
            local resp_time=$(echo "$line" | cut -d'|' -f2)
            
            if [ "$status" = "SUCCESS" ]; then
                ((success_count++))
                response_times+=("$resp_time")
            else
                ((error_count++))
            fi
        fi
    done < "$pid_file"
    
    rm -f "$pid_file"
    
    local end_time=$(date +%s.%N)
    local total_duration=$(echo "$end_time - $start_time" | bc -l)
    
    # Calculate metrics
    local avg_response_time=0
    if [ ${#response_times[@]} -gt 0 ]; then
        local sum=0
        for rt in "${response_times[@]}"; do
            sum=$(echo "$sum + $rt" | bc -l)
        done
        avg_response_time=$(echo "$sum / ${#response_times[@]}" | bc -l)
    fi
    
    local min_response_time=$(printf '%s\n' "${response_times[@]}" | sort -n | head -1)
    local max_response_time=$(printf '%s\n' "${response_times[@]}" | sort -n | tail -1)
    local throughput=$(echo "$NUM_TOTAL_REQUESTS $total_duration" | awk '{printf "%.2f", $1/$2}')
    local error_rate=$(echo "$error_count $NUM_TOTAL_REQUESTS" | awk '{printf "%.2f", $1/$2*100}')
    
    log_echo "${GREEN}✅ Search Gateway Benchmark Results:${NC}"
    log_echo "  Requests:        $NUM_TOTAL_REQUESTS"
    log_echo "  Successful:      $success_count"
    log_echo "  Failed:          $error_count"
    log_echo "  Error Rate:      ${error_rate}%"
    log_echo "  Total Time:      $(format_time $total_duration)"
    log_echo "  Avg Response:    $(format_time $avg_response_time)"
    log_echo "  Min Response:    $(format_time $min_response_time)"
    log_echo "  Max Response:    $(format_time $max_response_time)"
    log_echo "  Throughput:      ${throughput} RPS"
    log_echo ""
    
    # Performance rating
    if (( $(echo "$throughput > 5" | bc -l) )); then
        log_echo "${GREEN}  💪 PERFORMANCE: Excellent${NC}"
    elif (( $(echo "$throughput > 2" | bc -l) )); then
        log_echo "${YELLOW}  ⚡ PERFORMANCE: Good${NC}"
    elif (( $(echo "$throughput > 0.5" | bc -l) )); then
        log_echo "${BLUE}  👌 PERFORMANCE: Acceptable${NC}"
    else
        log_echo "${RED}  🐌 PERFORMANCE: Poor${NC}"
    fi
    
    # Save detailed results
    cat << EOF > "$REPORT_DIR/search_results_$TIMESTAMP.json"
{
  "benchmark": "Search Gateway",
  "timestamp": "$TIMESTAMP",
  "requests_sent": $NUM_TOTAL_REQUESTS,
  "successful_requests": $success_count,
  "failed_requests": $error_count,
  "total_duration": $total_duration,
  "avg_response_time": $avg_response_time,
  "min_response_time": $min_response_time,
  "max_response_time": $max_response_time,
  "throughput": $throughput,
  "error_rate": $error_rate,
  "response_times": [$(printf '%s,' "${response_times[@]}" | sed 's/,$//')]
}
EOF
}

# Function to check service health
check_services_health() {
    log_echo "${YELLOW}🏥 Checking service health...${NC}"
    
    check_service "Crawler Service" "http://localhost:8004/health"
    check_service "Search Gateway" "http://localhost:8003/health"
    check_service "LLM Gateway" "http://localhost:8081/health" 
    check_service "DeepSearch" "http://localhost:8001/health"
    
    log_echo ""
}

# Main benchmark execution
main() {
    log_echo "${CYAN}Commencing DeepSearchStack Base Benchmark Suite${NC}"
    log_echo "Testing realistic usage patterns under concurrent load"
    log_echo ""
    
    # Check health of services first
    check_services_health
    
    # Run benchmarks
    run_crawler_benchmark
    run_search_benchmark
    
    # Final summary
    log_echo "${GREEN}🎯 BENCHMARK SUITE COMPLETED${NC}"
    log_echo "${BLUE}Reports saved to:${NC} $REPORT_DIR"
    log_echo "${BLUE}Detailed results:${NC} $REPORT_DIR/*_$TIMESTAMP.json"
}

# Run the benchmark
main "$@"