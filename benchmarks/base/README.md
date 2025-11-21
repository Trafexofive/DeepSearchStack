# DeepSearchStack - Base Benchmark Suite

Comprehensive performance testing for the core DeepSearchStack services. These benchmarks simulate realistic usage patterns with concurrent requests to test scalability and responsiveness.

## Overview

The benchmark suite includes tests for:

1. **Crawler Service**: Concurrent web scraping performance with realistic URLs
2. **Search Gateway**: Query aggregation and response times under load
3. **LLM Gateway**: AI response performance with multiple concurrent requests

## Prerequisites

Before running benchmarks, ensure the DeepSearchStack services are running:

```bash
# Start all services
make up

# Or with docker-compose directly
docker compose -f infra/docker-compose.yml up -d
```

Verify services are healthy:

- Crawler: `http://localhost:8004/health` 
- Search Gateway: `http://localhost:8003/health`
- LLM Gateway: `http://localhost:8081/health`

## Running Benchmarks

### Quick Start

```bash
# Run the full benchmark suite
python benchmarks/base/run_benchmarks.py

# Run with custom base URL
python benchmarks/base/run_benchmarks.py --base-url http://localhost:8080

# Run a quick benchmark (fewer requests)
python benchmarks/base/run_benchmarks.py --quick
```

### With Different Concurrency Levels

```bash
# Adjust concurrency based on your system capacity
CONCURRENCY=10 python benchmarks/base/run_benchmarks.py
```

## Benchmark Types

### 1. Crawler Performance Test

- Tests concurrent crawling of multiple URLs
- Measures response times and success rates
- Simulates realistic web scraping patterns

### 2. Search Gateway Test

- Tests query aggregation performance
- Measures search response times under load
- Validates result quality consistency

### 3. LLM Gateway Test

- Tests AI response performance
- Measures token generation speeds
- Validates API stability under load

## Metrics Measured

Each benchmark captures:

- **Throughput**: Requests per second (RPS)
- **Latency**: Average, min, and max response times
- **Success Rate**: Percentage of successful requests
- **Error Rate**: Percentage of failed requests
- **Concurrent Performance**: Behavior under various load levels

## Performance Indicators

### Crawler Service
- Good: > 5 RPS with < 2s average response time
- Acceptable: 1-5 RPS with < 5s average response time
- Needs Improvement: < 1 RPS or > 5s average response time

### Search Gateway
- Good: > 10 RPS with < 1s average response time
- Acceptable: 2-10 RPS with < 2s average response time
- Needs Improvement: < 2 RPS or > 2s average response time

### LLM Gateway
- Good: > 2 RPS with < 10s average response time
- Acceptable: 0.5-2 RPS with < 15s average response time
- Needs Improvement: < 0.5 RPS or > 15s average response time

## Interpreting Results

Results are saved in JSON format in the `reports/` directory with timestamps. Each test will show:

- Performance classification (💪 Excellent, ⚡ Good, 👌 Acceptable, 🐌 Poor)
- Detailed metrics breakdown
- Error analysis
- Recommendations based on measured performance

## Running Continuous Benchmarks

For 24/7 operation testing:

```bash
# Run benchmarks in a loop with pauses
while true; do
    python benchmarks/base/run_benchmarks.py
    echo "Waiting 5 minutes before next run..."
    sleep 300
done
```

## Troubleshooting

### Common Issues

1. **Service Not Available**: Ensure all services are running and healthy before starting benchmarks
2. **High Error Rates**: May indicate insufficient system resources or external API limitations
3. **Low Performance**: Check system resource usage and network conditions

### System Requirements

- At least 4GB RAM (8GB+ recommended for higher concurrency)
- 2+ CPU cores
- Stable internet connection for external API calls
- Sufficient disk space for Docker images and logs

## Extending Benchmarks

To add custom benchmarks, extend the `DeepSearchBenchmark` class in `load_test.py` with new test methods following the same pattern as existing benchmarks.