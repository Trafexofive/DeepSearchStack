# DeepSearchStack - Realistic Benchmarks

Real-world performance testing that simulates actual business intelligence workflows using the full DeepSearchStack pipeline.

## Overview

Unlike synthetic performance tests, these benchmarks simulate actual business use cases:

1. **Goal Setting**: Define a business objective (e.g., "Analyze AI market trends")
2. **Data Ingestion**: Gather relevant information from web sources
3. **Aggregation**: Combine insights from multiple sources
4. **Transformation**: Process raw data into strategic intelligence
5. **Reporting**: Generate actionable reports and case studies
6. **Quality Validation**: Assess the value and accuracy of outputs

## Business Intelligence Pipeline Benchmark

The `business_intelligence_bench.py` script runs a complete business intelligence workflow:

- **Input**: Business goal like "Analyze current AI industry trends"
- **Processing**: 
  - Identifies key research questions
  - Searches for relevant information
  - Crawls top sources for detailed content
  - Aggregates insights across sources
  - Transforms data into strategic recommendations
  - Generates executive reports and case studies
- **Output**: Complete business intelligence package with actionable insights

## Running the Benchmark

```bash
# Run the complete business intelligence benchmark
python -m benchmarks.realistic.business_intelligence_bench

# The benchmark will:
# 1. Define a business intelligence goal
# 2. Ingest data through searches and crawls
# 3. Aggregate findings from multiple sources
# 4. Transform data into strategic insights  
# 5. Generate reports and case studies
# 6. Validate output quality
# 7. Produce performance metrics
```

## Key Metrics Measured

- **Success Rate**: Percentage of operations that complete successfully
- **Response Time**: Average time for each operation
- **Throughput**: Operations per minute
- **Data Quality**: Accuracy and relevance of aggregated insights
- **Pipeline Completeness**: End-to-end workflow success

## Performance Ratings

- **🔥 EXCELLENT**: >95% success rate, <5s avg response - Production ready
- **✅ GOOD**: >85% success rate, <10s avg response - Minor tuning needed
- **👍 ACCEPTABLE**: >70% success rate, <20s avg response - Some improvements needed
- **⚠️ NEEDS WORK**: <70% success rate or >20s avg response - Significant improvements needed

## Expected Results

A healthy DeepSearchStack deployment should achieve:
- Near 100% success rate for crawl and search operations
- Sub-5 second average response times for most operations
- Complete generation of business intelligence reports
- Meaningful case studies and strategic recommendations