#include "http_server.h"
#include "microservice.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <sstream>

HttpServer::HttpServer(Microservice& service) : service_(service), running_(false) {
    // Constructor implementation
}

HttpServer::~HttpServer() {
    stop();
}

bool HttpServer::start(const std::string& host, int port) {
    std::cout << "Starting HTTP server on " << host << ":" << port << std::endl;
    
    // Register default routes
    get("/health", [](const std::map<std::string, std::string>& params) -> std::string {
        return "{\"status\": \"healthy\", \"service\": \"cpp-microservice\"}";
    });
    
    get("/version", [](const std::map<std::string, std::string>& params) -> std::string {
        return "{\"version\": \"1.0.0\", \"service\": \"cpp-microservice\"}";
    });
    
    running_ = true;
    
    // Simulate server loop in a separate thread
    std::thread server_thread([this, host, port]() {
        while (running_) {
            // Simulate handling requests
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    });
    
    // Detach the thread (in a real implementation, you might want to join it properly)
    server_thread.detach();
    
    return true;
}

void HttpServer::stop() {
    if (running_) {
        std::cout << "Stopping HTTP server" << std::endl;
        running_ = false;
    }
}

void HttpServer::get(const std::string& path, const RequestHandler& handler) {
    get_handlers_[path] = handler;
    std::cout << "Registered GET route: " << path << std::endl;
}

void HttpServer::post(const std::string& path, const RequestHandler& handler) {
    post_handlers_[path] = handler;
    std::cout << "Registered POST route: " << path << std::endl;
}