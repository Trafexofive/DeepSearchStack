#include "microservice.h"
#include "config_manager.h"
#include <signal.h>
#include <unistd.h>
#include <cstring>

// Global pointer to microservice for signal handler
static Microservice* g_microservice = nullptr;

// Signal handler for graceful shutdown
void signalHandler(int signum) {
    std::cout << "Interrupt signal (" << signum << ") received." << std::endl;
    
    if (g_microservice) {
        g_microservice->shutdown();
    }
}

Microservice::Microservice() {
    // Register this instance for signal handling
    g_microservice = this;
}

Microservice::~Microservice() {
    g_microservice = nullptr;
}

bool Microservice::initialize() {
    std::cout << "Initializing microservice..." << std::endl;
    
    // Load configuration
    if (!loadConfig()) {
        std::cerr << "Failed to load configuration" << std::endl;
        return false;
    }
    
    // Setup signal handlers
    setupSignalHandlers();
    
    std::cout << "Microservice initialized successfully" << std::endl;
    return true;
}

int Microservice::run() {
    std::cout << "Starting microservice..." << std::endl;
    
    // Get configuration values
    std::string host = config_["HOST"];
    int port = std::stoi(config_["PORT"]);
    
    std::cout << "Microservice running on " << host << ":" << port << std::endl;
    
    // Main execution loop
    // This is where you would start your HTTP server, database connections, etc.
    while (true) {
        // Simulate work
        sleep(1);
        
        // Check for shutdown signal
        // In a real implementation, this would be handled by the server
    }
    
    return 0;
}

void Microservice::shutdown() {
    std::cout << "Shutting down microservice..." << std::endl;
    
    // Cleanup resources
    // Close database connections, stop HTTP server, etc.
}

bool Microservice::loadConfig() {
    ConfigManager configManager;
    if (!configManager.load()) {
        std::cerr << "Failed to load configuration" << std::endl;
        return false;
    }
    
    // Load configuration values
    config_["HOST"] = configManager.get("HOST", "0.0.0.0");
    config_["PORT"] = configManager.get("PORT", "8080");
    config_["LOG_LEVEL"] = configManager.get("LOG_LEVEL", "info");
    config_["DB_HOST"] = configManager.get("DB_HOST", "localhost");
    config_["DB_PORT"] = configManager.get("DB_PORT", "5432");
    config_["DB_NAME"] = configManager.get("DB_NAME", "microservice");
    config_["DB_USER"] = configManager.get("DB_USER", "microservice");
    config_["DB_PASS"] = configManager.get("DB_PASS", "password");
    
    return true;
}

void Microservice::setupSignalHandlers() {
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);
}