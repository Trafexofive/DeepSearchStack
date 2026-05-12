#include "microservice.h"
#include "http_server.h"
#include <iostream>

// Example of extending the microservice with a custom endpoint
class CustomMicroservice : public Microservice {
public:
    CustomMicroservice() : Microservice() {}
    
    bool initialize() override {
        // Call parent initialization
        if (!Microservice::initialize()) {
            return false;
        }
        
        // Add custom initialization here
        std::cout << "Custom microservice initialized" << std::endl;
        return true;
    }
    
    int run() override {
        std::cout << "Starting custom microservice..." << std::endl;
        
        // Start HTTP server with custom routes
        HttpServer server(*this);
        server.start("0.0.0.0", 8080);
        
        // Register custom routes
        server.get("/custom", [](const std::map<std::string, std::string>& params) -> std::string {
            return "{\"message\": \"Hello from custom endpoint\"}";
        });
        
        server.post("/custom", [](const std::map<std::string, std::string>& params) -> std::string {
            return "{\"message\": \"Custom POST endpoint received data\"}";
        });
        
        // Call parent run method
        return Microservice::run();
    }
};

int main(int argc, char* argv[]) {
    CustomMicroservice service;
    
    if (!service.initialize()) {
        std::cerr << "Failed to initialize custom microservice" << std::endl;
        return 1;
    }
    
    return service.run();
}