#ifndef DSS_HPP
#define DSS_HPP

// ==========================================================================
// DeepSearchStack (DSS) — C++17 Header-Only SDK
//
// Single header covering all 7 DSS services.
// HTTP transport via libcurl. JSON parsing minimal hand-rolled.
//
// Requires: libcurl (OpenSSL/GnuTLS), C++17 compiler
//
// All classes in namespace dss.
// All methods throw std::runtime_error on transport or protocol errors.
// ==========================================================================

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <winsock2.h>
#include <windows.h>
#endif
#include <curl/curl.h>

// ==========================================================================
// Detail helpers
// ==========================================================================

namespace dss {
namespace detail {

// --------------------------------------------------------------------------
// libcurl write callback
// --------------------------------------------------------------------------
inline size_t write_callback(void* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* str = static_cast<std::string*>(userdata);
    const size_t total = size * nmemb;
    str->append(static_cast<const char*>(ptr), total);
    return total;
}

// --------------------------------------------------------------------------
// Global curl initialisation (called once per process)
// --------------------------------------------------------------------------
inline bool curl_global_init_once() noexcept {
    static bool initialised = false;
    static bool success = false;
    if (!initialised) {
        initialised = true;
        success = (curl_global_init(CURL_GLOBAL_ALL) == CURLE_OK);
    }
    return success;
}

// --------------------------------------------------------------------------
// HTTP GET helper
// --------------------------------------------------------------------------
inline std::string http_get(const std::string& url,
                            const std::string& api_key = "",
                            long timeout = 30) {
    if (!curl_global_init_once()) {
        throw std::runtime_error("dss: curl_global_init failed");
    }

    CURL* curl = curl_easy_init();
    if (!curl) {
        throw std::runtime_error("dss: curl_easy_init failed");
    }

    std::string response;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 5L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "DSS-CPP-SDK/0.1.0");

    if (!api_key.empty()) {
        const std::string auth = "X-API-Key: " + api_key;
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, auth.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(headers);
        if (res != CURLE_OK) {
            curl_easy_cleanup(curl);
            throw std::runtime_error(std::string("dss: http_get failed: ") +
                                     curl_easy_strerror(res));
        }
    } else {
        CURLcode res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            curl_easy_cleanup(curl);
            throw std::runtime_error(std::string("dss: http_get failed: ") +
                                     curl_easy_strerror(res));
        }
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (http_code >= 400) {
        throw std::runtime_error("dss: http_get returned HTTP " +
                                 std::to_string(http_code) + " from " + url +
                                 ": " + response);
    }

    return response;
}

// --------------------------------------------------------------------------
// HTTP POST helper
// --------------------------------------------------------------------------
inline std::string http_post(const std::string& url,
                             const std::string& json_body,
                             const std::string& api_key = "",
                             long timeout = 120) {
    if (!curl_global_init_once()) {
        throw std::runtime_error("dss: curl_global_init failed");
    }

    CURL* curl = curl_easy_init();
    if (!curl) {
        throw std::runtime_error("dss: curl_easy_init failed");
    }

    std::string response;
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    if (!api_key.empty()) {
        const std::string auth = "X-API-Key: " + api_key;
        headers = curl_slist_append(headers, auth.c_str());
    }

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)json_body.size());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "DSS-CPP-SDK/0.1.0");

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);

    if (res != CURLE_OK) {
        curl_easy_cleanup(curl);
        throw std::runtime_error(std::string("dss: http_post failed: ") +
                                 curl_easy_strerror(res));
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (http_code >= 400) {
        throw std::runtime_error("dss: http_post returned HTTP " +
                                 std::to_string(http_code) + " from " + url +
                                 ": " + response);
    }

    return response;
}

// --------------------------------------------------------------------------
// HTTP DELETE helper
// --------------------------------------------------------------------------
inline std::string http_delete(const std::string& url,
                               const std::string& json_body = "",
                               const std::string& api_key = "",
                               long timeout = 30) {
    if (!curl_global_init_once()) {
        throw std::runtime_error("dss: curl_global_init failed");
    }

    CURL* curl = curl_easy_init();
    if (!curl) {
        throw std::runtime_error("dss: curl_easy_init failed");
    }

    std::string response;
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    if (!api_key.empty()) {
        const std::string auth = "X-API-Key: " + api_key;
        headers = curl_slist_append(headers, auth.c_str());
    }

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
    if (!json_body.empty()) {
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)json_body.size());
    }
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "DSS-CPP-SDK/0.1.0");

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);

    if (res != CURLE_OK) {
        curl_easy_cleanup(curl);
        throw std::runtime_error(std::string("dss: http_delete failed: ") +
                                 curl_easy_strerror(res));
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (http_code >= 400) {
        throw std::runtime_error("dss: http_delete returned HTTP " +
                                 std::to_string(http_code) + " from " + url +
                                 ": " + response);
    }

    return response;
}

// --------------------------------------------------------------------------
// Trim whitespace
// --------------------------------------------------------------------------
inline std::string trim(const std::string& s) {
    if (s.empty()) return s;
    size_t start = 0;
    while (start < s.size() && (s[start] == ' ' || s[start] == '\t' ||
                                s[start] == '\n' || s[start] == '\r'))
        ++start;
    size_t end = s.size();
    while (end > start && (s[end - 1] == ' ' || s[end - 1] == '\t' ||
                           s[end - 1] == '\n' || s[end - 1] == '\r'))
        --end;
    return s.substr(start, end - start);
}

// --------------------------------------------------------------------------
// JSON string unescape
// --------------------------------------------------------------------------
inline std::string json_unescape(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '\\' && i + 1 < s.size()) {
            switch (s[i + 1]) {
                case '"':  out.push_back('"'); ++i; break;
                case '\\': out.push_back('\\'); ++i; break;
                case '/':  out.push_back('/'); ++i; break;
                case 'b':  out.push_back('\b'); ++i; break;
                case 'f':  out.push_back('\f'); ++i; break;
                case 'n':  out.push_back('\n'); ++i; break;
                case 'r':  out.push_back('\r'); ++i; break;
                case 't':  out.push_back('\t'); ++i; break;
                case 'u': {
                    // Simple unicode escape — just pass through for now
                    if (i + 5 < s.size()) {
                        out += s.substr(i, 6);
                        i += 5;
                    }
                    break;
                }
                default:
                    out.push_back(s[i]);
                    break;
            }
        } else {
            out.push_back(s[i]);
        }
    }
    return out;
}

// --------------------------------------------------------------------------
// Find a JSON key and return the position after the colon and whitespace
// Returns std::string::npos if not found.
// --------------------------------------------------------------------------
inline size_t json_find_key(const std::string& json, const std::string& key) {
    // Search for "key":
    const std::string pat = "\"" + key + "\":";
    size_t pos = 0;
    while (true) {
        pos = json.find(pat, pos);
        if (pos == std::string::npos) return std::string::npos;

        // Verify not inside a string by counting quotes before pos
        bool in_string = false;
        size_t check = 0;
        while (check < pos) {
            if (json[check] == '"' && (check == 0 || json[check - 1] != '\\'))
                in_string = !in_string;
            ++check;
        }
        if (!in_string) {
            // Return position after the colon and whitespace
            pos += pat.size();
            while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                         json[pos] == '\n' || json[pos] == '\r'))
                ++pos;
            return pos;
        }
        ++pos;
    }
}

// --------------------------------------------------------------------------
// Extract a string value by key from a JSON object
// --------------------------------------------------------------------------
inline std::string json_str(const std::string& json, const std::string& key) {
    size_t start = json_find_key(json, key);
    if (start == std::string::npos || start >= json.size())
        return {};

    if (json[start] != '"') return {};

    ++start; // skip opening quote
    std::string result;
    bool escaped = false;
    for (size_t i = start; i < json.size(); ++i) {
        if (escaped) {
            if (json[i] == '"') result.push_back('"');
            else if (json[i] == '\\') result.push_back('\\');
            else if (json[i] == 'n') result.push_back('\n');
            else if (json[i] == 't') result.push_back('\t');
            else if (json[i] == 'r') result.push_back('\r');
            else if (json[i] == '/') result.push_back('/');
            else if (json[i] == 'u') {
                // Raw passthrough
                result += "\\u";
                for (int k = 0; k < 4 && i + 1 < json.size(); ++k) {
                    result.push_back(json[++i]);
                }
            }
            else result.push_back(json[i]);
            escaped = false;
        } else if (json[i] == '\\') {
            escaped = true;
        } else if (json[i] == '"') {
            return result;
        } else {
            result.push_back(json[i]);
        }
    }
    return result;
}

// --------------------------------------------------------------------------
// Extract a numeric value by key (returns 0.0 if not found)
// --------------------------------------------------------------------------
inline double json_num(const std::string& json, const std::string& key) {
    size_t start = json_find_key(json, key);
    if (start == std::string::npos || start >= json.size())
        return 0.0;

    // Check for null
    if (json.compare(start, 4, "null") == 0) return 0.0;

    size_t end = start;
    if (json[end] == '-') ++end;
    while (end < json.size() && (std::isdigit(static_cast<unsigned char>(json[end])) ||
                                 json[end] == '.' || json[end] == 'e' ||
                                 json[end] == 'E' || json[end] == '+' ||
                                 json[end] == '-'))
        ++end;

    try {
        return std::stod(json.substr(start, end - start));
    } catch (...) {
        return 0.0;
    }
}

// --------------------------------------------------------------------------
// Extract an integer value by key (returns 0 if not found)
// --------------------------------------------------------------------------
inline int json_int(const std::string& json, const std::string& key) {
    size_t start = json_find_key(json, key);
    if (start == std::string::npos || start >= json.size())
        return 0;

    // Check for null
    if (json.compare(start, 4, "null") == 0) return 0;

    size_t end = start;
    if (json[end] == '-') ++end;
    while (end < json.size() && std::isdigit(static_cast<unsigned char>(json[end])))
        ++end;

    try {
        return std::stoi(json.substr(start, end - start));
    } catch (...) {
        return 0;
    }
}

// --------------------------------------------------------------------------
// Extract a boolean value by key
// --------------------------------------------------------------------------
inline bool json_bool(const std::string& json, const std::string& key) {
    size_t pos = json_find_key(json, key);
    if (pos == std::string::npos || pos >= json.size())
        return false;

    if (json.compare(pos, 4, "true") == 0) return true;
    if (json.compare(pos, 5, "false") == 0) return false;
    return false;
}

// --------------------------------------------------------------------------
// Extract a JSON string value at a given position.
// --------------------------------------------------------------------------
inline std::string extract_json_string(const std::string& json, size_t start) {
    if (start >= json.size() || json[start] != '"') return {};
    ++start;
    std::string result;
    bool escaped = false;
    for (size_t i = start; i < json.size(); ++i) {
        if (escaped) {
            if (json[i] == '"') result.push_back('"');
            else if (json[i] == '\\') result.push_back('\\');
            else if (json[i] == 'n') result.push_back('\n');
            else if (json[i] == 't') result.push_back('\t');
            else if (json[i] == 'r') result.push_back('\r');
            else if (json[i] == '/') result.push_back('/');
            else if (json[i] == 'u') {
                result += "\\u";
                for (int k = 0; k < 4 && i + 1 < json.size(); ++k)
                    result.push_back(json[++i]);
            }
            else result.push_back(json[i]);
            escaped = false;
        } else if (json[i] == '\\') {
            escaped = true;
        } else if (json[i] == '"') {
            return result;
        } else {
            result.push_back(json[i]);
        }
    }
    return result;
}

// --------------------------------------------------------------------------
// Extract a numeric value at a given position.
// --------------------------------------------------------------------------
inline double extract_json_number(const std::string& json, size_t start) {
    size_t end = start;
    if (json[end] == '-') ++end;
    while (end < json.size() && (std::isdigit(static_cast<unsigned char>(json[end])) ||
                                 json[end] == '.' || json[end] == 'e' ||
                                 json[end] == 'E' || json[end] == '+' ||
                                 json[end] == '-'))
        ++end;
    try {
        return std::stod(json.substr(start, end - start));
    } catch (...) {
        return 0.0;
    }
}

// --------------------------------------------------------------------------
// Extract a JSON value as raw string (handles all types)
// --------------------------------------------------------------------------
inline std::string extract_json_value(const std::string& json, size_t start) {
    if (start >= json.size()) return {};

    char c = json[start];
    if (c == '"') return extract_json_string(json, start);
    if (c == 't' && json.compare(start, 4, "true") == 0) return "true";
    if (c == 'f' && json.compare(start, 5, "false") == 0) return "false";
    if (c == 'n' && json.compare(start, 4, "null") == 0) return "null";
    if (c == '-' || std::isdigit(static_cast<unsigned char>(c))) {
        size_t end = start;
        if (json[end] == '-') ++end;
        while (end < json.size() && (std::isdigit(static_cast<unsigned char>(json[end])) ||
                                     json[end] == '.' || json[end] == 'e' ||
                                     json[end] == 'E' || json[end] == '+' ||
                                     json[end] == '-'))
            ++end;
        return json.substr(start, end - start);
    }
    if (c == '{' || c == '[') {
        // Brace/bracket counting
        char open = c;
        char close = (c == '{') ? '}' : ']';
        int depth = 1;
        size_t i = start + 1;
        bool in_str = false;
        while (i < json.size() && depth > 0) {
            char ch = json[i];
            if (in_str) {
                if (ch == '\\') { ++i; }
                else if (ch == '"') { in_str = false; }
            } else if (ch == '"') {
                in_str = true;
            } else if (ch == open) {
                ++depth;
            } else if (ch == close) {
                --depth;
            }
            ++i;
        }
        return json.substr(start, i - start);
    }
    return {};
}

// --------------------------------------------------------------------------
// Extract array of values as vector of raw JSON strings
// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// Skip a single JSON value starting at `start`, return position after it.
// --------------------------------------------------------------------------
inline size_t skip_json_value(const std::string& json, size_t start) {
    if (start >= json.size()) return start;

    char c = json[start];
    if (c == '"') {
        // String
        ++start;
        while (start < json.size()) {
            if (json[start] == '\\') { start += 2; continue; }
            if (json[start] == '"') { ++start; break; }
            ++start;
        }
        return start;
    }
    if (c == '{' || c == '[') {
        char open = c;
        char close = (c == '{') ? '}' : ']';
        int depth = 1;
        bool in_str = false;
        ++start;
        while (start < json.size() && depth > 0) {
            if (in_str) {
                if (json[start] == '\\') { start += 2; continue; }
                if (json[start] == '"') { in_str = false; }
            } else if (json[start] == '"') {
                in_str = true;
            } else if (json[start] == open) {
                ++depth;
            } else if (json[start] == close) {
                --depth;
            }
            ++start;
        }
        return start;
    }
    if (c == 't' && json.compare(start, 4, "true") == 0) return start + 4;
    if (c == 'f' && json.compare(start, 5, "false") == 0) return start + 5;
    if (c == 'n' && json.compare(start, 4, "null") == 0) return start + 4;
    // Number
    size_t end = start;
    if (json[end] == '-') ++end;
    while (end < json.size() && (std::isdigit(static_cast<unsigned char>(json[end])) ||
                                 json[end] == '.' || json[end] == 'e' ||
                                 json[end] == 'E' || json[end] == '+' ||
                                 json[end] == '-'))
        ++end;
    return end;
}

inline std::vector<std::string> json_array(const std::string& json,
                                           const std::string& key) {
    std::vector<std::string> result;

    size_t start = json_find_key(json, key);
    if (start == std::string::npos || start >= json.size() ||
        json[start] != '[')
        return result;

    ++start; // skip [

    while (start < json.size()) {
        // Skip whitespace and commas
        while (start < json.size() && (json[start] == ' ' || json[start] == '\t' ||
                                       json[start] == '\n' || json[start] == '\r' ||
                                       json[start] == ','))
            ++start;

        if (start >= json.size() || json[start] == ']')
            break;

        // Extract the raw element and advance past it
        size_t elem_end = skip_json_value(json, start);
        result.push_back(json.substr(start, elem_end - start));
        start = elem_end;
    }

    return result;
}

// --------------------------------------------------------------------------
// Extract array of object-strings by a JSON key
// objects are delimited by {}
// --------------------------------------------------------------------------
inline std::vector<std::string> json_object_array(const std::string& json,
                                                   const std::string& key) {
    std::vector<std::string> result;

    size_t start = json_find_key(json, key);
    if (start == std::string::npos || start >= json.size() ||
        json[start] != '[')
        return result;

    ++start; // skip [
    while (start < json.size() && (json[start] == ' ' || json[start] == '\t' ||
                                   json[start] == '\n' || json[start] == '\r'))
        ++start;

    if (start < json.size() && json[start] == ']')
        return result;

    while (start < json.size()) {
        // Skip commas and whitespace
        while (start < json.size() && (json[start] == ',' || json[start] == ' ' ||
                                       json[start] == '\t' || json[start] == '\n' ||
                                       json[start] == '\r'))
            ++start;

        if (start >= json.size() || json[start] == ']')
            break;

        if (json[start] == '{') {
            int depth = 1;
            size_t i = start + 1;
            bool in_str = false;
            while (i < json.size() && depth > 0) {
                char ch = json[i];
                if (in_str) {
                    if (ch == '\\') { ++i; }
                    else if (ch == '"') { in_str = false; }
                } else if (ch == '"') {
                    in_str = true;
                } else if (ch == '{') {
                    ++depth;
                } else if (ch == '}') {
                    --depth;
                }
                ++i;
            }
            result.push_back(json.substr(start, i - start));
            start = i;
        } else {
            break;
        }
    }

    return result;
}

// --------------------------------------------------------------------------
// Build URL with query parameters (no external dependencies)
// --------------------------------------------------------------------------
inline std::string url_encode(const std::string& s) {
    std::string result;
    result.reserve(s.size() * 2);
    for (unsigned char c : s) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~')
            result.push_back(c);
        else {
            char buf[4];
            std::snprintf(buf, sizeof(buf), "%%%02X", c);
            result += buf;
        }
    }
    return result;
}

inline std::string build_url(const std::string& base,
                             const std::vector<std::pair<std::string, std::string>>& params) {
    if (params.empty()) return base;
    std::string url = base;
    bool first = (base.find('?') == std::string::npos);
    for (const auto& [key, value] : params) {
        url += first ? '?' : '&';
        first = false;
        url += url_encode(key);
        url += '=';
        url += url_encode(value);
    }
    return url;
}

// --------------------------------------------------------------------------
// Escape a string for JSON (minimal — surrounds with quotes and escapes)
// --------------------------------------------------------------------------
inline std::string json_escape(const std::string& s) {
    std::string result;
    result.reserve(s.size() + 8);
    result.push_back('"');
    for (unsigned char c : s) {
        switch (c) {
            case '"':  result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\b': result += "\\b";  break;
            case '\f': result += "\\f";  break;
            case '\n': result += "\\n";  break;
            case '\r': result += "\\r";  break;
            case '\t': result += "\\t";  break;
            default:
                if (c < 0x20) {
                    char buf[7];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    result += buf;
                } else {
                    result.push_back(c);
                }
                break;
        }
    }
    result.push_back('"');
    return result;
}

} // namespace detail

// ==========================================================================
// 1. CrawlerClient (port 8000)
// ==========================================================================

struct CrawlResult {
    std::string url;
    std::string content;
    std::string markdown;
    std::string title;
    std::string author;
    std::string published;
    std::string language;
    int word_count = 0;
    std::string source_domain;
    bool success = false;
    std::string error_type;
    std::string error_message;
    double crawled_at = 0.0;
    bool cache_hit = false;

    static CrawlResult from_json(const std::string& json) {
        CrawlResult r;
        r.url          = detail::json_str(json, "url");
        r.content      = detail::json_str(json, "content");
        r.markdown     = detail::json_str(json, "markdown");
        r.title        = detail::json_str(json, "title");
        r.author       = detail::json_str(json, "author");
        r.published    = detail::json_str(json, "published");
        r.language     = detail::json_str(json, "language");
        r.word_count   = detail::json_int(json, "word_count");
        r.source_domain = detail::json_str(json, "source_domain");
        r.success      = detail::json_bool(json, "success");
        r.error_type   = detail::json_str(json, "error_type");
        r.error_message = detail::json_str(json, "error_message");
        r.crawled_at   = detail::json_num(json, "crawled_at");
        r.cache_hit    = detail::json_bool(json, "cache_hit");
        return r;
    }
};

struct BatchCrawlResult {
    std::vector<CrawlResult> results;
    int success_count = 0;
    int failure_count = 0;
    int cache_hits = 0;
    double total_duration_ms = 0.0;

    static BatchCrawlResult from_json(const std::string& json) {
        BatchCrawlResult b;
        b.success_count     = detail::json_int(json, "success_count");
        b.failure_count     = detail::json_int(json, "failure_count");
        b.cache_hits        = detail::json_int(json, "cache_hits");
        b.total_duration_ms = detail::json_num(json, "total_duration_ms");

        auto objs = detail::json_object_array(json, "results");
        b.results.reserve(objs.size());
        for (const auto& obj : objs) {
            b.results.push_back(CrawlResult::from_json(obj));
        }
        return b;
    }
};

struct CacheDomainStat {
    std::string domain;
    int count = 0;

    static CacheDomainStat from_json(const std::string& json) {
        CacheDomainStat d;
        d.domain = detail::json_str(json, "domain");
        d.count  = detail::json_int(json, "count");
        return d;
    }
};

struct CacheStats {
    int total_entries = 0;
    int fresh_entries = 0;
    std::vector<CacheDomainStat> domains;

    static CacheStats from_json(const std::string& json) {
        CacheStats s;
        s.total_entries = detail::json_int(json, "total_entries");
        s.fresh_entries = detail::json_int(json, "fresh_entries");

        auto objs = detail::json_object_array(json, "domains");
        s.domains.reserve(objs.size());
        for (const auto& obj : objs) {
            s.domains.push_back(CacheDomainStat::from_json(obj));
        }
        return s;
    }
};

class CrawlerClient {
public:
    explicit CrawlerClient(std::string base_url = "http://localhost:8000",
                           std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        // Strip trailing slash
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    CrawlResult crawl(const std::string& url,
                      const std::string& extraction_strategy = "markdown",
                      int timeout = 30,
                      bool bypass_cache = false,
                      int cache_ttl_override = 0) {
        std::string body = "{";
        body += "\"url\": " + detail::json_escape(url) + ",";
        body += "\"extraction_strategy\": " + detail::json_escape(extraction_strategy) + ",";
        body += "\"timeout\": " + std::to_string(timeout) + ",";
        body += "\"bypass_cache\": " + std::string(bypass_cache ? "true" : "false");
        if (cache_ttl_override > 0) {
            body += ",\"cache_ttl_override\": " + std::to_string(cache_ttl_override);
        }
        body += "}";

        std::string response = detail::http_post(base_url_ + "/crawl", body,
                                                  api_key_, timeout + 10);
        return CrawlResult::from_json(response);
    }

    BatchCrawlResult crawl_batch(const std::vector<std::string>& urls,
                                  const std::string& extraction_strategy = "markdown",
                                  int timeout = 30,
                                  bool bypass_cache = false) {
        std::string body = "{\"urls\": [";
        for (size_t i = 0; i < urls.size(); ++i) {
            if (i > 0) body += ",";
            body += detail::json_escape(urls[i]);
        }
        body += "],";
        body += "\"extraction_strategy\": " + detail::json_escape(extraction_strategy) + ",";
        body += "\"timeout\": " + std::to_string(timeout) + ",";
        body += "\"bypass_cache\": " + std::string(bypass_cache ? "true" : "false");
        body += "}";

        std::string response = detail::http_post(base_url_ + "/crawl/batch", body,
                                                  api_key_, timeout + 15);
        return BatchCrawlResult::from_json(response);
    }

    CacheStats cache_stats() {
        std::string response = detail::http_get(base_url_ + "/cache/stats",
                                                 api_key_, 15);
        return CacheStats::from_json(response);
    }

    bool cache_clear() {
        std::string response = detail::http_post(base_url_ + "/cache/clear",
                                                  "{}", api_key_, 15);
        return detail::json_bool(response, "cleared");
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 2. DeepSearchClient (port 8001, deprecated/proxied)
// ==========================================================================

struct QuickSearchResult {
    std::string query;
    std::string answer;
    double execution_time = 0.0;

    static QuickSearchResult from_json(const std::string& json) {
        QuickSearchResult r;
        r.query          = detail::json_str(json, "query");
        r.answer         = detail::json_str(json, "answer");
        r.execution_time = detail::json_num(json, "execution_time");
        return r;
    }
};

struct SessionInfo {
    std::string session_id;
    std::string created_at;
    std::string updated_at;
    std::string title;
    std::string metadata_json;

    static SessionInfo from_json(const std::string& json) {
        SessionInfo s;
        s.session_id  = detail::json_str(json, "session_id");
        // Also check for "id"
        if (s.session_id.empty())
            s.session_id = detail::json_str(json, "id");
        s.created_at  = detail::json_str(json, "created_at");
        s.updated_at  = detail::json_str(json, "updated_at");
        s.title       = detail::json_str(json, "title");
        return s;
    }
};

struct SessionList {
    std::vector<SessionInfo> sessions;
    int total = 0;

    static SessionList from_json(const std::string& json) {
        SessionList sl;
        sl.total = detail::json_int(json, "total");

        auto objs = detail::json_object_array(json, "sessions");
        sl.sessions.reserve(objs.size());
        for (const auto& obj : objs) {
            sl.sessions.push_back(SessionInfo::from_json(obj));
        }
        return sl;
    }
};

class DeepSearchClient {
public:
    explicit DeepSearchClient(std::string base_url = "http://localhost:8001",
                              std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    QuickSearchResult quick_search(const std::string& query,
                                    int max_results = 10) {
        std::string body = "{";
        body += "\"query\": " + detail::json_escape(query) + ",";
        body += "\"max_results\": " + std::to_string(max_results);
        body += "}";

        std::string response = detail::http_post(base_url_ + "/deepsearch/quick",
                                                  body, api_key_, 60);
        return QuickSearchResult::from_json(response);
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

    SessionInfo create_session() {
        std::string response = detail::http_post(base_url_ + "/sessions",
                                                  "{}", api_key_, 15);
        return SessionInfo::from_json(response);
    }

    SessionInfo get_session(const std::string& session_id) {
        std::string response = detail::http_get(base_url_ + "/sessions/" +
                                                 session_id, api_key_, 15);
        return SessionInfo::from_json(response);
    }

    SessionList list_sessions(int limit = 50, int offset = 0) {
        auto params = detail::build_url(base_url_ + "/sessions", {
            {"limit", std::to_string(limit)},
            {"offset", std::to_string(offset)}
        });
        std::string response = detail::http_get(params, api_key_, 15);
        return SessionList::from_json(response);
    }

    bool delete_session(const std::string& session_id) {
        std::string url = base_url_ + "/sessions/" + session_id;
        std::string response = detail::http_delete(url, "", api_key_, 15);
        // May return {"deleted": session_id} or {"status": "deleted"}
        return true;
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 3. SearchGatewayClient (port 8002)
// ==========================================================================

struct SearchResultItem {
    std::string title;
    std::string url;
    std::string description;
    std::string source;
    double confidence = 0.0;
    double domain_authority = 0.0;
    int rank = 0;
    std::string timestamp;

    static SearchResultItem from_json(const std::string& json) {
        SearchResultItem item;
        item.title            = detail::json_str(json, "title");
        item.url              = detail::json_str(json, "url");
        item.description      = detail::json_str(json, "description");
        item.source           = detail::json_str(json, "source");
        item.confidence       = detail::json_num(json, "confidence");
        item.domain_authority = detail::json_num(json, "domain_authority");
        item.rank             = detail::json_int(json, "rank");
        item.timestamp        = detail::json_str(json, "published_date");
        if (item.timestamp.empty())
            item.timestamp    = detail::json_str(json, "timestamp");
        return item;
    }
};

class SearchGatewayClient {
public:
    explicit SearchGatewayClient(std::string base_url = "http://localhost:8002",
                                 std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    std::vector<SearchResultItem> search(const std::string& query,
                                          const std::vector<std::string>& providers = {},
                                          int max_results = 10,
                                          const std::string& sort_by = "relevance",
                                          int timeout = 15) {
        std::string body = "{";
        body += "\"query\": " + detail::json_escape(query) + ",";
        body += "\"providers\": [";
        for (size_t i = 0; i < providers.size(); ++i) {
            if (i > 0) body += ",";
            body += detail::json_escape(providers[i]);
        }
        body += "],";
        body += "\"max_results\": " + std::to_string(max_results) + ",";
        body += "\"sort_by\": " + detail::json_escape(sort_by) + ",";
        body += "\"timeout\": " + std::to_string(timeout);
        body += "}";

        std::string response = detail::http_post(base_url_ + "/search", body,
                                                  api_key_, timeout + 15);

        // Response is a JSON array of objects
        std::vector<SearchResultItem> results;
        auto objs = detail::json_object_array(response, "");

        // If json_object_array with empty key doesn't work, try parsing as top-level array
        if (objs.empty()) {
            // Check if the entire response is an array
            size_t pos = 0;
            while (pos < response.size() && (response[pos] == ' ' ||
                                             response[pos] == '\t' ||
                                             response[pos] == '\n' ||
                                             response[pos] == '\r'))
                ++pos;
            if (pos < response.size() && response[pos] == '[') {
                ++pos;
                // Skip whitespace
                while (pos < response.size() && (response[pos] == ' ' ||
                                                 response[pos] == '\t' ||
                                                 response[pos] == '\n' ||
                                                 response[pos] == '\r'))
                    ++pos;

                while (pos < response.size()) {
                    // Skip commas and whitespace
                    while (pos < response.size() && (response[pos] == ',' ||
                                                     response[pos] == ' ' ||
                                                     response[pos] == '\t' ||
                                                     response[pos] == '\n' ||
                                                     response[pos] == '\r'))
                        ++pos;

                    if (pos >= response.size() || response[pos] == ']')
                        break;

                    if (response[pos] == '{') {
                        int depth = 1;
                        size_t i = pos + 1;
                        bool in_str = false;
                        while (i < response.size() && depth > 0) {
                            char ch = response[i];
                            if (in_str) {
                                if (ch == '\\') { ++i; }
                                else if (ch == '"') { in_str = false; }
                            } else if (ch == '"') {
                                in_str = true;
                            } else if (ch == '{') {
                                ++depth;
                            } else if (ch == '}') {
                                --depth;
                            }
                            ++i;
                        }
                        objs.push_back(response.substr(pos, i - pos));
                        pos = i;
                    } else {
                        break;
                    }
                }
            }
        }

        results.reserve(objs.size());
        for (const auto& obj : objs) {
            results.push_back(SearchResultItem::from_json(obj));
        }
        return results;
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

    std::string providers() {
        return detail::http_get(base_url_ + "/providers", api_key_, 15);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 4. SearchAgentClient (port 8013)
// ==========================================================================

struct SynthesizeRequest {
    std::string query;
    std::vector<SearchResultItem> sources;
    std::string llm_provider;

    std::string to_json() const {
        std::string body = "{";
        body += "\"query\": " + detail::json_escape(query) + ",";
        body += "\"sources\": [";
        for (size_t i = 0; i < sources.size(); ++i) {
            if (i > 0) body += ",";
            body += "{";
            body += "\"title\": " + detail::json_escape(sources[i].title) + ",";
            body += "\"url\": " + detail::json_escape(sources[i].url) + ",";
            body += "\"description\": " + detail::json_escape(sources[i].description);
            body += "}";
        }
        body += "]";
        if (!llm_provider.empty()) {
            body += ",\"llm_provider\": " + detail::json_escape(llm_provider);
        }
        body += "}";
        return body;
    }
};

class SearchAgentClient {
public:
    explicit SearchAgentClient(std::string base_url = "http://localhost:8013",
                               std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    // Returns raw SSE (Server-Sent Events) text
    std::string synthesize_stream(const std::string& query,
                                   const std::vector<SearchResultItem>& sources = {},
                                   const std::string& llm_provider = "") {
        SynthesizeRequest req;
        req.query = query;
        req.sources = sources;
        req.llm_provider = llm_provider;

        return detail::http_post(base_url_ + "/synthesize/stream",
                                  req.to_json(), api_key_, 180);
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 5. WarehouseClient (port 8009)
// ==========================================================================

struct IngestResponse {
    int id = 0;
    std::string url;
    bool ingested = false;
    bool cached = false;

    static IngestResponse from_json(const std::string& json) {
        IngestResponse r;
        r.id       = detail::json_int(json, "id");
        r.url      = detail::json_str(json, "url");
        r.ingested = detail::json_bool(json, "ingested");
        r.cached   = detail::json_bool(json, "cached");
        return r;
    }
};

struct ContentItem {
    int id = 0;
    std::string url;
    std::string title;
    std::string markdown;
    std::string author;
    std::string published;
    std::string language;
    int word_count = 0;
    std::string source_domain;
    std::string ingested_at;
    std::vector<std::string> tags;

    static ContentItem from_json(const std::string& json) {
        ContentItem item;
        item.id            = detail::json_int(json, "id");
        item.url           = detail::json_str(json, "url");
        item.title         = detail::json_str(json, "title");
        item.markdown      = detail::json_str(json, "markdown");
        item.author        = detail::json_str(json, "author");
        item.published     = detail::json_str(json, "published");
        item.language      = detail::json_str(json, "language");
        item.word_count    = detail::json_int(json, "word_count");
        item.source_domain = detail::json_str(json, "source_domain");
        item.ingested_at   = detail::json_str(json, "ingested_at");

        auto arr = detail::json_array(json, "tags");
        item.tags.reserve(arr.size());
        for (const auto& t : arr) {
            // Each element is a quoted string — unescape
            std::string tag = detail::trim(t);
            if (tag.size() >= 2 && tag.front() == '"' && tag.back() == '"')
                tag = tag.substr(1, tag.size() - 2);
            item.tags.push_back(detail::json_unescape(tag));
        }
        return item;
    }
};

struct SearchHit {
    int id = 0;
    std::string url;
    std::string title;
    std::string snippet;
    std::string source_domain;
    std::string ingested_at;
    int word_count = 0;

    static SearchHit from_json(const std::string& json) {
        SearchHit hit;
        hit.id            = detail::json_int(json, "id");
        hit.url           = detail::json_str(json, "url");
        hit.title         = detail::json_str(json, "title");
        hit.snippet       = detail::json_str(json, "snippet");
        hit.source_domain = detail::json_str(json, "source_domain");
        hit.ingested_at   = detail::json_str(json, "ingested_at");
        hit.word_count    = detail::json_int(json, "word_count");
        return hit;
    }
};

struct ListEntry {
    int id = 0;
    std::string url;
    std::string title;
    std::string snippet;
    std::string source_domain;
    std::string ingested_at;
    int word_count = 0;
    std::string author;
    std::vector<std::string> tags;

    static ListEntry from_json(const std::string& json) {
        ListEntry entry;
        entry.id            = detail::json_int(json, "id");
        entry.url           = detail::json_str(json, "url");
        entry.title         = detail::json_str(json, "title");
        entry.snippet       = detail::json_str(json, "snippet");
        entry.source_domain = detail::json_str(json, "source_domain");
        entry.ingested_at   = detail::json_str(json, "ingested_at");
        entry.word_count    = detail::json_int(json, "word_count");
        entry.author        = detail::json_str(json, "author");

        auto arr = detail::json_array(json, "tags");
        entry.tags.reserve(arr.size());
        for (const auto& t : arr) {
            std::string tag = detail::trim(t);
            if (tag.size() >= 2 && tag.front() == '"' && tag.back() == '"')
                tag = tag.substr(1, tag.size() - 2);
            entry.tags.push_back(detail::json_unescape(tag));
        }
        return entry;
    }
};

struct WarehouseDomainStat {
    std::string domain;
    int count = 0;

    static WarehouseDomainStat from_json(const std::string& json) {
        WarehouseDomainStat d;
        d.domain = detail::json_str(json, "domain");
        d.count  = detail::json_int(json, "count");
        return d;
    }
};

struct WarehouseStats {
    int total_entries = 0;
    int total_words = 0;
    std::vector<WarehouseDomainStat> domains;
    double db_size_mb = 0.0;

    static WarehouseStats from_json(const std::string& json) {
        WarehouseStats s;
        s.total_entries = detail::json_int(json, "total_entries");
        s.total_words   = detail::json_int(json, "total_words");
        s.db_size_mb    = detail::json_num(json, "db_size_mb");

        auto objs = detail::json_object_array(json, "domains");
        s.domains.reserve(objs.size());
        for (const auto& obj : objs) {
            s.domains.push_back(WarehouseDomainStat::from_json(obj));
        }
        return s;
    }
};

class WarehouseClient {
public:
    explicit WarehouseClient(std::string base_url = "http://localhost:8009",
                             std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    IngestResponse ingest(const std::string& url,
                           const std::string& markdown,
                           const std::string& content = "",
                           const std::string& title = "",
                           const std::string& author = "",
                           const std::string& published = "",
                           const std::string& language = "",
                           int word_count = 0,
                           const std::string& source_domain = "",
                           const std::vector<std::string>& tags = {}) {
        std::string body = "{";
        body += "\"url\": " + detail::json_escape(url) + ",";
        body += "\"markdown\": " + detail::json_escape(markdown);
        if (!content.empty())
            body += ",\"content\": " + detail::json_escape(content);
        if (!title.empty())
            body += ",\"title\": " + detail::json_escape(title);
        if (!author.empty())
            body += ",\"author\": " + detail::json_escape(author);
        if (!published.empty())
            body += ",\"published\": " + detail::json_escape(published);
        if (!language.empty())
            body += ",\"language\": " + detail::json_escape(language);
        if (word_count > 0)
            body += ",\"word_count\": " + std::to_string(word_count);
        if (!source_domain.empty())
            body += ",\"source_domain\": " + detail::json_escape(source_domain);
        if (!tags.empty()) {
            body += ",\"tags\": [";
            for (size_t i = 0; i < tags.size(); ++i) {
                if (i > 0) body += ",";
                body += detail::json_escape(tags[i]);
            }
            body += "]";
        }
        body += "}";

        std::string response = detail::http_post(base_url_ + "/ingest", body,
                                                  api_key_, 30);
        return IngestResponse::from_json(response);
    }

    ContentItem get_content(int item_id) {
        std::string response = detail::http_get(base_url_ + "/content/" +
                                                 std::to_string(item_id),
                                                 api_key_, 15);
        return ContentItem::from_json(response);
    }

    std::vector<SearchHit> search(const std::string& q,
                                   int limit = 20,
                                   const std::string& domain = "") {
        std::vector<std::pair<std::string, std::string>> params;
        params.emplace_back("q", q);
        params.emplace_back("limit", std::to_string(limit));
        if (!domain.empty())
            params.emplace_back("domain", domain);

        std::string url = detail::build_url(base_url_ + "/search", params);
        std::string response = detail::http_get(url, api_key_, 15);

        return parse_result_array<SearchHit>(response);
    }

    std::vector<ListEntry> list_entries(const std::string& sort = "ingested_at",
                                         const std::string& order = "desc",
                                         int offset = 0,
                                         int limit = 30,
                                         const std::string& domain = "") {
        std::vector<std::pair<std::string, std::string>> params;
        params.emplace_back("sort", sort);
        params.emplace_back("order", order);
        params.emplace_back("offset", std::to_string(offset));
        params.emplace_back("limit", std::to_string(limit));
        if (!domain.empty())
            params.emplace_back("domain", domain);

        std::string url = detail::build_url(base_url_ + "/list", params);
        std::string response = detail::http_get(url, api_key_, 15);

        return parse_result_array<ListEntry>(response);
    }

    WarehouseStats stats() {
        std::string response = detail::http_get(base_url_ + "/stats",
                                                 api_key_, 15);
        return WarehouseStats::from_json(response);
    }

    bool delete_content(int item_id) {
        std::string response = detail::http_delete(base_url_ + "/content/" +
                                                    std::to_string(item_id),
                                                    "", api_key_, 15);
        return response.find("\"deleted\"") != std::string::npos;
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

private:
    template<typename T>
    std::vector<T> parse_result_array(const std::string& json) {
        std::vector<T> results;
        auto objs = detail::json_object_array(json, "");
        if (objs.empty()) {
            size_t pos = 0;
            while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                         json[pos] == '\n' || json[pos] == '\r'))
                ++pos;
            if (pos < json.size() && json[pos] == '[') {
                ++pos;
                while (pos < json.size()) {
                    while (pos < json.size() && (json[pos] == ',' ||
                                                 json[pos] == ' ' ||
                                                 json[pos] == '\t' ||
                                                 json[pos] == '\n' ||
                                                 json[pos] == '\r'))
                        ++pos;
                    if (pos >= json.size() || json[pos] == ']')
                        break;
                    if (json[pos] == '{') {
                        int depth = 1;
                        size_t i = pos + 1;
                        bool in_str = false;
                        while (i < json.size() && depth > 0) {
                            char ch = json[i];
                            if (in_str) {
                                if (ch == '\\') { ++i; }
                                else if (ch == '"') { in_str = false; }
                            } else if (ch == '"') {
                                in_str = true;
                            } else if (ch == '{') {
                                ++depth;
                            } else if (ch == '}') {
                                --depth;
                            }
                            ++i;
                        }
                        objs.push_back(json.substr(pos, i - pos));
                        pos = i;
                    } else {
                        break;
                    }
                }
            }
        }
        results.reserve(objs.size());
        for (const auto& obj : objs) {
            results.push_back(T::from_json(obj));
        }
        return results;
    }

    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 6. VectorStoreClient (port 8004)
// ==========================================================================

struct Document {
    std::string id;       // optional — leave empty to auto-generate
    std::string text;
    std::string metadata; // optional JSON string
    std::string url;      // optional
    std::string title;    // optional
};

struct EmbedResponse {
    std::string message;
    int count = 0;
    int total_docs = 0;

    static EmbedResponse from_json(const std::string& json) {
        EmbedResponse r;
        r.message    = detail::json_str(json, "message");
        r.count      = detail::json_int(json, "count");
        r.total_docs = detail::json_int(json, "total_docs");
        return r;
    }
};

struct QueryResponse {
    std::vector<std::vector<std::string>> ids;
    std::vector<std::vector<std::string>> documents;
    std::vector<std::vector<std::string>> metadatas;
    std::vector<std::vector<double>> distances;

    static QueryResponse from_json(const std::string& json) {
        QueryResponse qr;

        // Parse ids — may be [[str, str, ...]]
        auto id_arr = detail::json_array(json, "ids");
        if (!id_arr.empty()) {
            qr.ids.resize(1);
            for (const auto& s : id_arr) {
                std::string clean = detail::trim(s);
                if (clean.size() >= 2 && clean.front() == '"' && clean.back() == '"')
                    clean = clean.substr(1, clean.size() - 2);
                qr.ids[0].push_back(detail::json_unescape(clean));
            }
        } else {
            // Try nested array
            size_t pos = detail::json_find_key(json, "ids");
            if (pos != std::string::npos && pos < json.size() && json[pos] == '[') {
                ++pos;
                while (pos < json.size()) {
                    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                                 json[pos] == '\n' || json[pos] == '\r' ||
                                                 json[pos] == ','))
                        ++pos;
                    if (pos >= json.size() || json[pos] == ']')
                        break;
                    if (json[pos] == '[') {
                        ++pos;
                        std::vector<std::string> inner;
                        while (pos < json.size()) {
                            while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' ||
                                                         json[pos] == '\n' || json[pos] == '\r' ||
                                                         json[pos] == ','))
                                ++pos;
                            if (pos >= json.size() || json[pos] == ']') {
                                if (json[pos] == ']') ++pos;
                                break;
                            }
                            std::string val = detail::extract_json_string(json, pos);
                            inner.push_back(val);
                            pos += (val.empty() ? 1 : val.size() + 2);
                        }
                        qr.ids.push_back(inner);
                    }
                }
            }
        }

        // Parse documents
        auto doc_arr = detail::json_array(json, "documents");
        if (!doc_arr.empty()) {
            qr.documents.resize(1);
            for (const auto& s : doc_arr) {
                std::string clean = detail::trim(s);
                if (clean.size() >= 2 && clean.front() == '"' && clean.back() == '"')
                    clean = clean.substr(1, clean.size() - 2);
                qr.documents[0].push_back(detail::json_unescape(clean));
            }
        }

        // Parse metadatas
        auto meta_arr = detail::json_object_array(json, "metadatas");
        if (!meta_arr.empty()) {
            qr.metadatas.resize(1);
            qr.metadatas[0] = meta_arr;
        }

        // Parse distances
        auto dist_arr = detail::json_array(json, "distances");
        if (!dist_arr.empty()) {
            qr.distances.resize(1);
            for (const auto& s : dist_arr) {
                try {
                    qr.distances[0].push_back(std::stod(s));
                } catch (...) {}
            }
        }

        return qr;
    }
};

class VectorStoreClient {
public:
    explicit VectorStoreClient(std::string base_url = "http://localhost:8004",
                               std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    EmbedResponse embed(const std::vector<Document>& documents,
                         const std::string& namespace_ = "") {
        std::string body = "{";
        body += "\"documents\": [";
        for (size_t i = 0; i < documents.size(); ++i) {
            if (i > 0) body += ",";
            body += "{";
            body += "\"text\": " + detail::json_escape(documents[i].text);
            if (!documents[i].id.empty())
                body += ",\"id\": " + detail::json_escape(documents[i].id);
            if (!documents[i].metadata.empty())
                body += ",\"metadata\": " + documents[i].metadata;
            if (!documents[i].url.empty())
                body += ",\"url\": " + detail::json_escape(documents[i].url);
            if (!documents[i].title.empty())
                body += ",\"title\": " + detail::json_escape(documents[i].title);
            body += "}";
        }
        body += "]";
        if (!namespace_.empty())
            body += ",\"namespace\": " + detail::json_escape(namespace_);
        body += "}";

        std::string response = detail::http_post(base_url_ + "/embed", body,
                                                  api_key_, 60);
        return EmbedResponse::from_json(response);
    }

    QueryResponse query(const std::string& query_text,
                         int n_results = 5,
                         const std::string& namespace_ = "") {
        std::string body = "{";
        body += "\"query_text\": " + detail::json_escape(query_text) + ",";
        body += "\"n_results\": " + std::to_string(n_results);
        if (!namespace_.empty())
            body += ",\"namespace\": " + detail::json_escape(namespace_);
        body += "}";

        std::string response = detail::http_post(base_url_ + "/query", body,
                                                  api_key_, 30);
        return QueryResponse::from_json(response);
    }

    bool delete_documents(const std::vector<std::string>& ids = {},
                           const std::string& namespace_ = "",
                           bool delete_all = false) {
        std::string body = "{";
        if (!ids.empty()) {
            body += "\"ids\": [";
            for (size_t i = 0; i < ids.size(); ++i) {
                if (i > 0) body += ",";
                body += detail::json_escape(ids[i]);
            }
            body += "]";
        }
        if (!namespace_.empty()) {
            if (!ids.empty()) body += ",";
            body += "\"namespace\": " + detail::json_escape(namespace_);
        }
        if (delete_all) {
            if (!ids.empty() || !namespace_.empty()) body += ",";
            body += "\"delete_all\": true";
        }
        body += "}";

        std::string response = detail::http_delete(base_url_ + "/documents",
                                                    body, api_key_, 30);
        return true;
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

// ==========================================================================
// 7. WebAPIClient (port 8014)
// ==========================================================================

struct SourceResult {
    std::string title;
    std::string url;
    std::string description;
    std::string source;
    std::string domain;
    double confidence = 0.0;
    std::string summary;
    std::vector<std::string> entities;

    static SourceResult from_json(const std::string& json) {
        SourceResult sr;
        sr.title       = detail::json_str(json, "title");
        sr.url         = detail::json_str(json, "url");
        sr.description = detail::json_str(json, "description");
        sr.source      = detail::json_str(json, "source");
        sr.domain      = detail::json_str(json, "domain");
        sr.confidence  = detail::json_num(json, "confidence");
        sr.summary     = detail::json_str(json, "summary");

        auto arr = detail::json_array(json, "entities");
        sr.entities.reserve(arr.size());
        for (const auto& e : arr) {
            std::string clean = detail::trim(e);
            if (clean.size() >= 2 && clean.front() == '"' && clean.back() == '"')
                clean = clean.substr(1, clean.size() - 2);
            sr.entities.push_back(detail::json_unescape(clean));
        }
        return sr;
    }
};

struct AggregateResponse {
    std::string query;
    int total_sources = 0;
    std::vector<SourceResult> sources;
    double execution_time_ms = 0.0;
    std::string answer;
    std::string synthesis;
    std::vector<std::string> domains_queried;
    int scraped_urls = 0;
    int rag_chunks = 0;
    bool fact_db_hit = false;

    static AggregateResponse from_json(const std::string& json) {
        AggregateResponse ar;
        ar.query            = detail::json_str(json, "query");
        ar.total_sources    = detail::json_int(json, "total_sources");
        ar.execution_time_ms = detail::json_num(json, "execution_time_ms");
        ar.answer           = detail::json_str(json, "answer");
        ar.synthesis        = detail::json_str(json, "synthesis");
        ar.scraped_urls     = detail::json_int(json, "scraped_urls");
        ar.rag_chunks       = detail::json_int(json, "rag_chunks");
        ar.fact_db_hit      = detail::json_bool(json, "fact_db_hit");

        // Fallback: answer may be in "synthesis" field
        if (ar.answer.empty())
            ar.answer = detail::json_str(json, "synthesis");
        // Fallback: answer may be in "answer" field
        if (ar.answer.empty())
            ar.answer = detail::json_str(json, "answer");

        auto domains = detail::json_array(json, "domains_queried");
        ar.domains_queried.reserve(domains.size());
        for (const auto& d : domains) {
            std::string clean = detail::trim(d);
            if (clean.size() >= 2 && clean.front() == '"' && clean.back() == '"')
                clean = clean.substr(1, clean.size() - 2);
            ar.domains_queried.push_back(detail::json_unescape(clean));
        }

        auto objs = detail::json_object_array(json, "sources");
        ar.sources.reserve(objs.size());
        for (const auto& obj : objs) {
            ar.sources.push_back(SourceResult::from_json(obj));
        }
        return ar;
    }
};

class WebAPIClient {
public:
    explicit WebAPIClient(std::string base_url = "http://localhost:8014",
                          std::string api_key = "")
        : base_url_(std::move(base_url))
        , api_key_(std::move(api_key))
    {
        if (!base_url_.empty() && base_url_.back() == '/')
            base_url_.pop_back();
    }

    AggregateResponse aggregate(const std::string& query,
                                 int max_results = 10,
                                 bool include_warehouse = true,
                                 bool reconcile = true,
                                 bool enable_scraping = false,
                                 int max_scrape_urls = 5,
                                 bool enable_rag = false,
                                 int rag_top_k = 10,
                                 bool enable_synthesis = true) {
        std::string body = "{";
        body += "\"query\": " + detail::json_escape(query) + ",";
        body += "\"max_results\": " + std::to_string(max_results) + ",";
        body += "\"include_warehouse\": " + std::string(include_warehouse ? "true" : "false") + ",";
        body += "\"reconcile\": " + std::string(reconcile ? "true" : "false") + ",";
        body += "\"enable_scraping\": " + std::string(enable_scraping ? "true" : "false") + ",";
        body += "\"max_scrape_urls\": " + std::to_string(max_scrape_urls) + ",";
        body += "\"enable_rag\": " + std::string(enable_rag ? "true" : "false") + ",";
        body += "\"rag_top_k\": " + std::to_string(rag_top_k) + ",";
        body += "\"enable_synthesis\": " + std::string(enable_synthesis ? "true" : "false");
        body += "}";

        std::string response = detail::http_post(base_url_ + "/api/aggregate",
                                                  body, api_key_, 120);
        return AggregateResponse::from_json(response);
    }

    std::string health() {
        return detail::http_get(base_url_ + "/health", api_key_, 10);
    }

    std::string metrics() {
        return detail::http_get(base_url_ + "/api/metrics", api_key_, 15);
    }

    std::string facts(const std::string& q = "") {
        if (q.empty()) {
            return detail::http_get(base_url_ + "/api/facts", api_key_, 15);
        }
        std::string url = detail::build_url(base_url_ + "/api/facts",
                                             {{"q", q}});
        return detail::http_get(url, api_key_, 15);
    }

private:
    std::string base_url_;
    std::string api_key_;
};

} // namespace dss

#endif // DSS_HPP
