// ==========================================================================
// DSS C++ SDK — Usage Examples
//
// Build: g++ -std=c++17 -I.. main.cpp -lcurl -o dss_example
// Run:   ./dss_example
// ==========================================================================

#include "dss.hpp"
#include <iostream>
#include <iomanip>

// Example using WebAPIClient (main entry point)
void example_web_api() {
    std::cout << "\n=== WebAPIClient ===\n";
    dss::WebAPIClient api("http://localhost:8014");

    // Health check
    auto health = api.health();
    std::cout << "Health: " << health << "\n";

    // Aggregate search
    auto result = api.aggregate("What is WebAssembly?", 5);
    std::cout << "Query: " << result.query << "\n"
              << "Sources: " << result.total_sources << "\n"
              << "Time: " << result.execution_time_ms << "ms\n";
    for (const auto& s : result.sources) {
        std::cout << "  - " << s.title << " (" << s.domain << ")\n";
    }
    if (!result.answer.empty()) {
        std::cout << "Answer: " << result.answer.substr(0, 200) << "...\n";
    }
}

// Example using CrawlerClient
void example_crawler() {
    std::cout << "\n=== CrawlerClient ===\n";
    dss::CrawlerClient crawler("http://localhost:8000");

    // Crawl a URL
    auto result = crawler.crawl("https://example.com");
    if (result.success) {
        std::cout << "Crawled: " << result.url << "\n"
                  << "Title: " << result.title << "\n"
                  << "Words: " << result.word_count << "\n"
                  << "Cache hit: " << (result.cache_hit ? "yes" : "no") << "\n";
    } else {
        std::cout << "Crawl failed: " << result.error_message << "\n";
    }

    // Cache stats
    auto stats = crawler.cache_stats();
    std::cout << "Cache: " << stats.fresh_entries << " fresh / "
              << stats.total_entries << " total\n";
}

// Example using SearchGatewayClient
void example_search_gateway() {
    std::cout << "\n=== SearchGatewayClient ===\n";
    dss::SearchGatewayClient sg("http://localhost:8002");

    auto results = sg.search("Rust programming", {"searxng", "wikipedia"}, 5);
    std::cout << "Search results: " << results.size() << "\n";
    for (const auto& r : results) {
        std::cout << "  [" << r.source << "] " << r.title << "\n"
                  << "    " << r.url << "\n";
    }
}

// Example using WarehouseClient
void example_warehouse() {
    std::cout << "\n=== WarehouseClient ===\n";
    dss::WarehouseClient wh("http://localhost:8009");

    // Stats
    auto stats = wh.stats();
    std::cout << "Warehouse: " << stats.total_entries << " entries, "
              << stats.total_words << " words, "
              << stats.db_size_mb << " MB\n";

    // Search
    auto hits = wh.search("WebAssembly");
    std::cout << "Search hits: " << hits.size() << "\n";
    for (const auto& h : hits) {
        std::cout << "  " << h.title << " (" << h.source_domain << ")\n";
    }
}

// Example using VectorStoreClient
void example_vector_store() {
    std::cout << "\n=== VectorStoreClient ===\n";
    dss::VectorStoreClient vs("http://localhost:8004");

    // Health
    auto health = vs.health();
    std::cout << "Vector store health: " << health << "\n";

    // Embed a document
    dss::Document doc;
    doc.text = "WebAssembly is a binary instruction format for a stack-based virtual machine.";
    doc.metadata = "{\"source\": \"wikipedia\"}";
    auto embed = vs.embed({doc});
    std::cout << "Embedded: " << embed.count << " docs (total: " << embed.total_docs << ")\n";
}

int main() {
    std::cout << "DSS C++ SDK Examples\n"
              << "====================\n"
              << "Note: Run with DSS services up (docker compose up)\n";

    try {
        example_web_api();
    } catch (const std::exception& e) {
        std::cout << "WebAPI error (expected if service down): " << e.what() << "\n";
    }

    try {
        example_crawler();
    } catch (const std::exception& e) {
        std::cout << "Crawler error (expected if service down): " << e.what() << "\n";
    }

    try {
        example_search_gateway();
    } catch (const std::exception& e) {
        std::cout << "SearchGateway error (expected if service down): " << e.what() << "\n";
    }

    try {
        example_warehouse();
    } catch (const std::exception& e) {
        std::cout << "Warehouse error (expected if service down): " << e.what() << "\n";
    }

    try {
        example_vector_store();
    } catch (const std::exception& e) {
        std::cout << "VectorStore error (expected if service down): " << e.what() << "\n";
    }

    return 0;
}
