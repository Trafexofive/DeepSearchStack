# Self-Hosted Deep Search Agent Stack

## Architecture Overview

```
                    ┌─────────────────────┐
                    │    Web UI/CLI       │
                    │   (React/CLI)       │
                    └──────────┬──────────┘
                               │
                    ┌─────────────────────┐
                    │   API Gateway       │
                    │   (C++/Rust Core)   │
                    │ ┌─────────────────┐ │
                    │ │ Query Router    │ │
                    │ │ Result Fusion   │ │
                    │ │ Cache Layer     │ │
                    │ │ Rate Limiter    │ │
                    │ └─────────────────┘ │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼──────┐    ┌─────────▼──────┐    ┌─────────▼──────┐
│    YaCy      │    │   Whoogle      │    │  Local Index   │
│ (P2P Search) │    │ (Google Proxy) │    │ (Xapian/Custom)│
└──────────────┘    └────────────────┘    └────────────────┘
                               │
                    ┌─────────────────────┐
                    │   Storage Layer     │
                    │ ┌─────────────────┐ │
                    │ │  Vector Store   │ │
                    │ │  (Chroma/FAISS) │ │
                    │ │                 │ │
                    │ │  Metadata DB    │ │
                    │ │  (PostgreSQL)   │ │
                    │ │                 │ │
                    │ │  Document Store │ │
                    │ │  (File System)  │ │
                    │ └─────────────────┘ │
                    └─────────────────────┘
```

## Core Components

### 1. API Gateway (C++/Rust Core)

**Query Router & Orchestrator**
```cpp
// gateway/query_router.hpp
class QueryRouter {
private:
    std::vector<std::unique_ptr<SearchBackend>> backends;
    std::unique_ptr<ResultFusion> fusion_engine;
    std::unique_ptr<CacheManager> cache;
    
public:
    SearchResponse route_query(const SearchQuery& query);
    void add_backend(std::unique_ptr<SearchBackend> backend);
    void set_routing_strategy(RoutingStrategy strategy);
};

enum class RoutingStrategy {
    PARALLEL_ALL,      // Query all backends simultaneously
    PRIORITY_FALLBACK, // Try high-priority first, fallback if needed
    INTELLIGENT,       // ML-based routing based on query type
    LOAD_BALANCED     // Distribute based on backend load
};
```

**Result Fusion Engine**
```cpp
// gateway/result_fusion.hpp
class ResultFusion {
public:
    struct FusionConfig {
        float yacy_weight = 0.4f;
        float whoogle_weight = 0.4f;
        float local_weight = 0.2f;
        bool enable_deduplication = true;
        float similarity_threshold = 0.85f;
    };
    
    SearchResults fuse_results(
        const std::vector<BackendResults>& backend_results,
        const FusionConfig& config = {}
    );
    
private:
    float calculate_relevance_score(const SearchResult& result, 
                                  const SearchQuery& query);
    std::vector<SearchResult> deduplicate_results(
        const std::vector<SearchResult>& results
    );
};
```

### 2. Search Backends

**YaCy Integration**
```cpp
// backends/yacy_backend.hpp
class YaCyBackend : public SearchBackend {
private:
    std::string base_url;
    HttpClient client;
    
public:
    YaCyBackend(const std::string& url) : base_url(url) {}
    
    BackendResults search(const SearchQuery& query) override {
        // YaCy JSON API: /yacysearch.json
        auto response = client.get(base_url + "/yacysearch.json", {
            {"query", query.text},
            {"maximumRecords", std::to_string(query.limit)},
            {"startRecord", std::to_string(query.offset)}
        });
        return parse_yacy_response(response);
    }
    
    HealthStatus health_check() override;
    BackendStats get_stats() override;
};
```

**Whoogle Backend**
```cpp
// backends/whoogle_backend.hpp
class WhoogleBackend : public SearchBackend {
private:
    std::string base_url;
    HttpClient client;
    std::unique_ptr<HtmlParser> parser;
    
public:
    BackendResults search(const SearchQuery& query) override {
        // Whoogle search endpoint
        auto response = client.get(base_url + "/search", {
            {"q", query.text},
            {"num", std::to_string(query.limit)}
        });
        return parse_html_results(response.body);
    }
    
    void set_user_agent(const std::string& ua);
    void set_rate_limiting(int requests_per_minute);
};
```

**Local Index Backend**
```cpp
// backends/local_backend.hpp
class LocalIndexBackend : public SearchBackend {
private:
    std::unique_ptr<Xapian::Database> text_index;
    std::unique_ptr<VectorStore> vector_store;
    std::unique_ptr<EmbeddingModel> embedder;
    
public:
    BackendResults search(const SearchQuery& query) override {
        // Hybrid search: text + semantic
        auto text_results = search_text_index(query);
        auto vector_results = search_vector_store(query);
        return merge_hybrid_results(text_results, vector_results);
    }
    
    void index_document(const Document& doc);
    void reindex_all();
};
```

### 3. Advanced Gateway Features

**Intelligent Caching**
```cpp
// gateway/cache_manager.hpp
class CacheManager {
private:
    std::unique_ptr<RedisClient> redis;
    std::unordered_map<std::string, CachedResult> memory_cache;
    
public:
    std::optional<SearchResults> get_cached_results(const SearchQuery& query);
    void cache_results(const SearchQuery& query, const SearchResults& results);
    void invalidate_cache(const std::string& pattern = "*");
    
    // Smart caching strategies
    void enable_semantic_cache(float similarity_threshold = 0.9f);
    void enable_popularity_cache(int min_query_count = 5);
};
```

**Query Enhancement**
```cpp
// gateway/query_enhancer.hpp
class QueryEnhancer {
public:
    SearchQuery enhance_query(const SearchQuery& original) {
        SearchQuery enhanced = original;
        
        // Spell correction
        enhanced.text = spell_correct(enhanced.text);
        
        // Query expansion
        auto expanded_terms = expand_query_terms(enhanced.text);
        enhanced.expanded_terms = expanded_terms;
        
        // Intent detection
        enhanced.intent = detect_intent(enhanced.text);
        
        // Domain-specific routing hints
        enhanced.routing_hints = generate_routing_hints(enhanced);
        
        return enhanced;
    }
    
private:
    QueryIntent detect_intent(const std::string& query);
    std::vector<std::string> expand_query_terms(const std::string& query);
};
```

**Load Balancer & Circuit Breaker**
```cpp
// gateway/load_balancer.hpp
class LoadBalancer {
private:
    struct BackendHealth {
        bool is_healthy = true;
        int consecutive_failures = 0;
        std::chrono::steady_clock::time_point last_failure;
        float response_time_avg = 0.0f;
        int request_count = 0;
    };
    
    std::unordered_map<std::string, BackendHealth> backend_health;
    
public:
    std::vector<SearchBackend*> select_backends(const SearchQuery& query);
    void report_backend_result(const std::string& backend_id, 
                              bool success, 
                              float response_time);
    
    // Circuit breaker pattern
    bool is_backend_available(const std::string& backend_id);
};
```

### 3. Text Processing Pipeline

**Xapian** - C++ search engine library
```cpp
#include <xapian.h>

Xapian::WritableDatabase db("./search_index", 
                           Xapian::DB_CREATE_OR_OPEN);
Xapian::TermGenerator indexer;
Xapian::Stem stemmer("english");
indexer.set_stemmer(stemmer);
```

**Custom Tokenizer/Stemmer**
```c
// Minimal Porter Stemmer implementation
char* stem_word(char* word) {
    // Your C implementation here
    return word;
}
```

### 4. Embedding Models (Local)

**sentence-transformers** with local models
- all-MiniLM-L6-v2 (22MB)
- all-mpnet-base-v2 (420MB)
- No API calls, runs locally

**Custom Word2Vec/FastText**
```bash
# Train your own embeddings
./fasttext skipgram -input corpus.txt -output model -dim 300
```

### 4. Docker Compose Stack (Gateway-Centric)

```yaml
version: '3.8'

services:
  # Core API Gateway
  search-gateway:
    build: ./gateway
    ports:
      - "8080:8080"  # Main API endpoint
      - "8081:8081"  # Admin/metrics endpoint
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - GATEWAY_MODE=production
      - CACHE_BACKEND=redis
      - LOG_LEVEL=info
    depends_on:
      - redis
      - postgres
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Search Backends
  yacy:
    image: yacy/yacy_search_server:latest
    ports:
      - "8090:8090"
    volumes:
      - yacy_data:/opt/yacy_search_server/DATA
      - ./yacy_config:/opt/yacy_search_server/defaults
    environment:
      - YACY_MEMORY=2g
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/api/status.json"]

  whoogle:
    image: benbusby/whoogle-search:latest
    ports:
      - "5000:5000"
    environment:
      - WHOOGLE_ALT_TW=nitter.net
      - WHOOGLE_ALT_YT=piped.kavin.rocks
      - WHOOGLE_ALT_IG=bibliogram.art
      - WHOOGLE_ALT_RD=libredd.it
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]

  local-index:
    build: ./local-index
    ports:
      - "8082:8082"
    volumes:
      - index_data:/app/index
      - crawl_data:/app/documents
      - ./models:/app/models
    environment:
      - INDEX_TYPE=hybrid  # text+vector
      - EMBEDDING_MODEL=all-MiniLM-L6-v2

  # Infrastructure
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 1gb

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: searchdb
      POSTGRES_USER: searchuser
      POSTGRES_PASSWORD: searchpass
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql

  # Monitoring & Admin
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards

  # Document Processing Pipeline
  crawler:
    build: ./crawler
    volumes:
      - crawl_data:/app/data
      - ./crawler/config:/app/config
    environment:
      - CRAWL_SCHEDULE=0 2 * * *  # Daily at 2 AM
      - MAX_DEPTH=3
      - RESPECT_ROBOTS=true
    depends_on:
      - local-index

volumes:
  yacy_data:
  redis_data:
  postgres_data:
  prometheus_data:
  grafana_data:
  index_data:
  crawl_data:
```

### 5. Gateway Configuration

**Main Gateway Config**
```toml
# config/gateway.toml
[server]
host = "0.0.0.0"
port = 8080
workers = 8
max_connections = 1000

[backends]
  [backends.yacy]
  enabled = true
  url = "http://yacy:8090"
  weight = 0.4
  timeout = 5000  # ms
  max_retries = 2
  
  [backends.whoogle]
  enabled = true
  url = "http://whoogle:5000"
  weight = 0.4
  timeout = 3000
  max_retries = 1
  
  [backends.local]
  enabled = true
  url = "http://local-index:8082"
  weight = 0.2
  timeout = 1000
  max_retries = 0

[fusion]
strategy = "weighted_score"
deduplication = true
similarity_threshold = 0.85
max_results = 50

[cache]
backend = "redis"
ttl = 3600  # 1 hour
max_memory = "500mb"
semantic_cache = true
semantic_threshold = 0.9

[rate_limiting]
enabled = true
requests_per_minute = 100
burst_size = 20
```

**CLI Interface**
```bash
# gateway/cli/search_cli.sh
#!/bin/bash

GATEWAY_URL="http://localhost:8080"

search() {
    local query="$1"
    local format="${2:-json}"
    local backends="${3:-all}"
    
    curl -s "${GATEWAY_URL}/search" \
        -H "Content-Type: application/json" \
        -d "{
            \"query\": \"${query}\",
            \"format\": \"${format}\",
            \"backends\": \"${backends}\",
            \"limit\": 20
        }" | jq .
}

health_check() {
    curl -s "${GATEWAY_URL}/health" | jq .
}

stats() {
    curl -s "${GATEWAY_URL}/admin/stats" | jq .
}

case "$1" in
    "search") search "$2" "$3" "$4" ;;
    "health") health_check ;;
    "stats") stats ;;
    *) echo "Usage: $0 {search|health|stats} [args...]" ;;
esac
```

### 6. Advanced Features for Future Development

**Query Intelligence**
```cpp
// features/query_intelligence.hpp
class QueryIntelligence {
public:
    struct QueryAnalysis {
        QueryType type;           // web, academic, code, local
        std::vector<std::string> entities;
        float complexity_score;
        std::vector<std::string> suggested_backends;
    };
    
    QueryAnalysis analyze_query(const std::string& query);
    std::vector<std::string> generate_query_variations(const std::string& query);
    SearchQuery optimize_for_backend(const SearchQuery& query, 
                                   const std::string& backend_type);
};
```

**Result Enhancement**
```cpp
// features/result_enhancer.hpp
class ResultEnhancer {
public:
    // Post-process search results
    SearchResults enhance_results(const SearchResults& raw_results);
    
    // Extract key information
    std::vector<std::string> extract_key_facts(const SearchResult& result);
    
    // Generate result summaries
    std::string generate_summary(const std::vector<SearchResult>& results);
    
    // Related queries
    std::vector<std::string> suggest_related_queries(const SearchQuery& query,
                                                   const SearchResults& results);
};
```

**Backend Fusion Strategies**
```cpp
// features/fusion_strategies.hpp
enum class FusionStrategy {
    WEIGHTED_SCORE,    // Simple weighted combination
    RANK_FUSION,       // Reciprocal rank fusion
    BAYESIAN_FUSION,   // Bayesian combination
    ML_FUSION,         // Machine learning based
    CONSENSUS_FUSION   // Majority voting
};

class AdvancedFusion {
public:
    SearchResults fuse_with_strategy(
        const std::vector<BackendResults>& results,
        FusionStrategy strategy,
        const FusionParams& params
    );
    
    // Learn optimal fusion weights from user feedback
    void train_fusion_model(const std::vector<QueryResultPair>& training_data);
};
```

## Build & Deployment

### Build Instructions
```bash
# Project structure
deepsearch-stack/
├── gateway/           # C++ core gateway
├── backends/          # Backend implementations
├── crawler/           # Document crawler
├── local-index/       # Local search index
├── monitoring/        # Prometheus/Grafana configs
├── config/           # Configuration files
├── scripts/          # Build and deployment scripts
└── docker-compose.yml

# Build everything
./scripts/build_all.sh

# Or build components individually
cd gateway && mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=17 ..
make -j$(nproc)

# Start the stack
docker-compose up -d

# Initialize with seed data
./scripts/init_search_stack.sh
```

### Development Workflow
```bash
# scripts/dev_workflow.sh
#!/bin/bash

# Hot reload for gateway development
build_and_restart_gateway() {
    cd gateway/build
    make -j$(nproc) && docker-compose restart search-gateway
}

# Add new backend
add_backend() {
    local backend_name="$1"
    local backend_url="$2"
    
    curl -X POST "${GATEWAY_URL}/admin/backends" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${backend_name}\", \"url\": \"${backend_url}\"}"
}

# Test all backends
test_backends() {
    for backend in yacy whoogle local; do
        echo "Testing ${backend}..."
        curl -s "${GATEWAY_URL}/admin/backends/${backend}/test" | jq .
    done
}

# Performance benchmarking
benchmark() {
    echo "Running benchmark..."
    ./scripts/benchmark.sh
}
```

### Configuration Management
```bash
# config/search_config.sh
export SEARCH_PROVIDERS="yacy,local,searxng"
export VECTOR_MODEL="all-MiniLM-L6-v2"
export CRAWL_DOMAINS="wikipedia.org,stackoverflow.com,github.com"
export INDEX_UPDATE_INTERVAL="3600"  # 1 hour
export MAX_RESULTS_PER_PROVIDER="50"
```

## Free/Low-Limit External Services (Optional)

1. **HuggingFace Inference API** - 1000 requests/month free
2. **Ollama** - Run LLMs locally (llama2, codellama, etc.)
3. **Common Crawl** - Free web crawl data archives
4. **Internet Archive API** - Historical web pages

## Build Instructions

```bash
# Clone and setup
git clone <your-repo>
cd deepsearch-agent

# Build C++ components
mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Download models
python3 scripts/download_models.py

# Initialize databases
./scripts/init_db.sh

# Start services
docker-compose up -d
```

## Scaling Strategy

1. **Horizontal scaling**: Multiple crawler instances
2. **Caching**: Redis for frequent queries
3. **Load balancing**: nginx for API endpoints
4. **Distributed storage**: GlusterFS for large indices

## Monitoring

```bash
# monitoring/health_check.sh
#!/bin/bash

curl -f http://localhost:8000/health || exit 1
curl -f http://localhost:8001/vector/health || exit 1
psql -h localhost -U searchuser -d searchdb -c "SELECT 1;" || exit 1
```

This gives you a completely self-contained search stack with minimal external dependencies and maximum control over your data and search quality.
