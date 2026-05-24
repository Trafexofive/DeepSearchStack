#include "microservice.h"
#include <iostream>

int main(int argc, char* argv[]) {
    Microservice service;
    
    if (!service.initialize()) {
        std::cerr << "Failed to initialize microservice" << std::endl;
        return 1;
    }
    
    return service.run();
}