// substrate.hpp — C++17 header-only SDK for Substrate control plane
//
// Thin HTTP wrappers around each service. Dependency: libcurl.
// Language-agnostic microservices: this header talks HTTP/JSON only.
//
// Usage:
//   #include "substrate.hpp"
//   using namespace substrate;
//
//   BlogClient blog("http://localhost:80");
//   auto result = blog.generate("What is WebAssembly?");
//   std::cout << result.content << "\n";
//
// Build:
//   g++ -std=c++17 -lcurl your_app.cpp

#pragma once

#include <string>
#include <vector>
#include <optional>
#include <stdexcept>
#include <sstream>
#include <curl/curl.h>

namespace substrate {

// ─── Helpers ────────────────────────────────────────────────────────────────

namespace detail {
    inline size_t write_callback(void* contents, size_t size, size_t nmemb, void* userp) {
        auto* s = static_cast<std::string*>(userp);
        s->append(static_cast<char*>(contents), size * nmemb);
        return size * nmemb;
    }

    inline std::string http_post(const std::string& url, const std::string& json_body,
                                  const std::string& api_key = "", long timeout = 120) {
        CURL* curl = curl_easy_init();
        if (!curl) throw std::runtime_error("curl_easy_init failed");

        std::string response;
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        if (!api_key.empty()) {
            headers = curl_slist_append(headers, ("Authorization: Bearer " + api_key).c_str());
        }

        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);

        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);

        if (res != CURLE_OK) {
            throw std::runtime_error(std::string("curl error: ") + curl_easy_strerror(res));
        }
        return response;
    }

    inline std::string http_get(const std::string& url, const std::string& api_key = "",
                                 long timeout = 30) {
        CURL* curl = curl_easy_init();
        if (!curl) throw std::runtime_error("curl_easy_init failed");

        std::string response;
        struct curl_slist* headers = nullptr;
        if (!api_key.empty()) {
            headers = curl_slist_append(headers, ("Authorization: Bearer " + api_key).c_str());
        }

        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);

        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);

        if (res != CURLE_OK) {
            throw std::runtime_error(std::string("curl error: ") + curl_easy_strerror(res));
        }
        return response;
    }
}

// ─── Response Types ─────────────────────────────────────────────────────────

struct GenerateResponse {
    std::string id;
    std::string topic;
    std::string model;
    std::string content;
    int total_tokens = 0;
    double cost_usd = 0.0;
    int duration_ms = 0;
};

struct HealthResponse {
    std::string status;
    std::string version;
};

// ─── Blog Client ────────────────────────────────────────────────────────────

class BlogClient {
public:
    explicit BlogClient(std::string base_url = "http://localhost:80",
                        std::string api_key = "")
        : base_url_(std::move(base_url)), api_key_(std::move(api_key)) {}

    /// Generate a blog post on a topic. Blocks until complete (30-60s).
    GenerateResponse generate(const std::string& topic,
                              const std::string& model = "deepseek-chat",
                              const std::string& style = "technical",
                              int max_tokens = 2048,
                              double temperature = 0.7) {
        std::ostringstream body;
        body << R"({"topic":")" << topic
             << R"(","model":")" << model
             << R"(","style":")" << style
             << R"(","max_tokens":)" << max_tokens
             << R"(,"temperature":)" << temperature
             << "}";

        std::string json = detail::http_post(base_url_ + "/api/blog/generate", body.str(), api_key_);
        // Minimal JSON parse — for production, use nlohmann/json or simdjson
        // This parses just the fields the struct has.
        GenerateResponse r;
        auto find_val = [&](const std::string& key) -> std::string {
            auto pos = json.find("\"" + key + "\"");
            if (pos == std::string::npos) return "";
            auto val_start = json.find(":", pos);
            auto q_start = json.find("\"", val_start);
            auto q_end = json.find("\"", q_start + 1);
            if (q_start != std::string::npos && q_end != std::string::npos)
                return json.substr(q_start + 1, q_end - q_start - 1);
            // Numeric value
            auto comma = json.find(",", val_start);
            auto brace = json.find("}", val_start);
            auto end = std::min(comma, brace);
            return json.substr(val_start + 1, end - val_start - 1);
        };
        r.id = find_val("id");
        r.topic = find_val("topic");
        r.model = find_val("model");
        r.content = find_val("content");
        // Truncated: token/cost parsing simplified for header-only demo
        return r;
    }

    std::string health() {
        return detail::http_get(base_url_ + "/api/blog/health", api_key_);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ─── Workflow Client ────────────────────────────────────────────────────────

class WorkflowClient {
public:
    explicit WorkflowClient(std::string base_url = "http://localhost:80",
                            std::string api_key = "")
        : base_url_(std::move(base_url)), api_key_(std::move(api_key)) {}

    /// Execute a workflow DAG. Blocks until completion (60-120s).
    std::string execute(const std::string& workflow,
                        const std::string& params_json = "{}") {
        std::ostringstream body;
        body << R"({"workflow":")" << workflow
             << R"(","params":)" << params_json << "}";
        return detail::http_post(base_url_ + "/api/workflows/execute", body.str(), api_key_, 300);
    }

    /// Convenience: seo_content_loop pipeline
    std::string seo_content_loop(const std::string& topic,
                                  const std::string& keyword = "",
                                  const std::string& tone = "technical") {
        std::ostringstream params;
        params << R"({"topic":")" << topic
               << R"(","keyword":")" << (keyword.empty() ? topic : keyword)
               << R"(","tone":")" << tone << "\"}";
        return execute("seo_content_loop", params.str());
    }

    std::string list_workflows() {
        return detail::http_get(base_url_ + "/api/workflows", api_key_);
    }

    std::string health() {
        return detail::http_get(base_url_ + "/api/workflows/execute/health", api_key_);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ─── Ingest Client ──────────────────────────────────────────────────────────

class IngestClient {
public:
    explicit IngestClient(std::string base_url = "http://localhost:80",
                          std::string api_key = "")
        : base_url_(std::move(base_url)), api_key_(std::move(api_key)) {}

    std::string health() { return detail::http_get(base_url_ + "/api/ingest/health", api_key_); }
    std::string stats()  { return detail::http_get(base_url_ + "/api/ingest/stats", api_key_); }
    std::string feeds()  { return detail::http_get(base_url_ + "/api/ingest/feeds", api_key_); }
    std::string drafts() { return detail::http_get(base_url_ + "/api/ingest/drafts", api_key_); }

    std::string scan(const std::string& feed_url = "") {
        std::string body = feed_url.empty()
            ? "{}"
            : R"({"feed_url":")" + feed_url + "\"}";
        return detail::http_post(base_url_ + "/api/ingest/scan", body, api_key_);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ─── Inference Client ───────────────────────────────────────────────────────

class InferenceClient {
public:
    explicit InferenceClient(std::string base_url = "http://localhost:80",
                             std::string api_key = "")
        : base_url_(std::move(base_url)), api_key_(std::move(api_key)) {}

    std::string models() { return detail::http_get(base_url_ + "/api/inference/models", api_key_); }

    std::string chat(const std::string& model, const std::string& messages_json,
                     int max_tokens = 2048, double temperature = 0.7) {
        std::ostringstream body;
        body << R"({"model":")" << model
             << R"(","messages":)" << messages_json
             << R"(,"max_tokens":)" << max_tokens
             << R"(,"temperature":)" << temperature << "}";
        return detail::http_post(base_url_ + "/api/inference/chat/completions", body.str(), api_key_);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

} // namespace substrate
