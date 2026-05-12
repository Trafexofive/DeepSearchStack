# DeepSearchStack - Documentation Aggregator and Synthesizer

An agentic workflow that leverages the full power of DeepSearchStack to aggregate and synthesize documentation from URLs or search queries.

## Overview

This workflow implements a multi-agent system that can:

1. **Accept URLs or search terms** - Process documentation from provided URLs or search for relevant documentation
2. **Crawl content** - Extract content from web pages when URLs are provided
3. **Process through specialized agents** - Each agent performs a specific validation function:
   - **Test Agent**: Validates content structure and relevance
   - **Quality Check Agent**: Assesses content quality and completeness
   - **Security Audit Agent**: Scans for potential security concerns
   - **Synthesis Agent**: Creates comprehensive synthesis of the content
   - **Summary Agent**: Generates concise summaries
   - **Suggestions Agent**: Provides improvement recommendations

## Architecture

```
User Input (URL or Query)
        ↓
   ┌─────────────────┐
   │  URL Detection  │
   └─────────────────┘
         ↙    ↘
   ┌────────┐  ┌──────────┐
   │ Crawl  │  │  Search  │
   │  URL   │  │ & Crawl  │
   └────────┘  └──────────┘
        ↓           ↓
   ┌─────────────────────────┐
   │      Multi-Agent        │
   │    Processing Chain     │
   ├─────────────────────────┤
   │ • Test Agent            │
   │ • Quality Agent         │
   │ • Security Agent        │
   │ • Synthesis Agent       │
   │ • Summary Agent         │
   │ • Suggestions Agent     │
   └─────────────────────────┘
        ↓
   ┌─────────────────┐
   │  Unified Output │
   │ (Synthesis,     │
   │  Summary,       │
   │  Recommendations)│
   └─────────────────┘
```

## Features

- **Flexible Input**: Handles both direct URLs and search queries
- **Content Validation**: Ensures retrieved content is relevant and structured
- **Quality Assessment**: Evaluates content completeness with numerical scores
- **Security Scanning**: Identifies potential security issues in documentation
- **Intelligent Synthesis**: Creates well-organized syntheses from raw content
- **Actionable Suggestions**: Provides specific recommendations for improvement

## Usage

### Basic Usage

```bash
cd workflows/documentation-aggregator
python main.py
```

### As a Module

```python
from main import DocumentationProcessor

processor = DocumentationProcessor()

# Process from URL
result = processor.process_documentation("https://example.com/docs")

# Process from search term
result = processor.process_documentation("Python requests library documentation")

print(result.summary)
print(f"Quality Score: {result.quality_score}")
print(result.suggestions)
```

## Components

### `DocumentationProcessor`
Main orchestrator that manages the agent workflow and coordinates processing.

### `DocProcessingResult`
Data structure that encapsulates the complete result with all intermediate steps.

### Specialized Agents
- `_test_content_agent`: Validates content structure and relevance
- `_quality_check_agent`: Assesses content quality metrics
- `_security_audit_agent`: Scans for security concerns
- `_synthesis_agent`: Creates comprehensive content synthesis
- `_summary_agent`: Generates concise summaries
- `_suggestions_agent`: Provides improvement recommendations

## Example Output

```
📚 DeepSearchStack - Documentation Aggregator and Synthesizer
======================================================================
Example 1: Processing documentation from URL
--------------------------------------------------
✅ Query: https://example.com
📖 Source: https://example.com
🔍 Summary: Example Domain This domain is for use in illustrative examples in documents...
✅ Quality Score: 0.15
⚠️  Security Warnings: 0
💡 Suggestions: 3

Example 2: Processing documentation from search term
--------------------------------------------------
✅ Query: Python API basics
📖 Source: https://some-python-docs.com/api-basics
🔍 Summary: Python APIs provide interfaces for programmatically accessing functionality...
✅ Quality Score: 0.68
⚠️  Security Warnings: 1
💡 Suggestions: 5

🎯 Documentation processing workflow completed!
```

## Benefits

- **Comprehensive Analysis**: Multi-dimensional assessment of documentation quality
- **Security Awareness**: Proactive identification of security-sensitive content
- **Actionable Intelligence**: Concrete suggestions for documentation improvement
- **Scalable Architecture**: Can handle multiple concurrent documentation requests
- **Quality Metrics**: Provides measurable quality scores for documentation evaluation