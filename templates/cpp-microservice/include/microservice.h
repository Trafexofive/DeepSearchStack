#ifndef MICROSERVICE_H
#define MICROSERVICE_H

#include <string>
#include <memory>
#include <iostream>
#include <fstream>
#include <map>

// Forward declarations
class HttpServer;
class Database;

/**
 * @brief Main Microservice class
 * 
 * This class represents the core of the C++ microservice.
 * It handles initialization, configuration loading, and main execution loop.
 */
class Microservice {
public:
    /**
     * @brief Construct a new Microservice object
     */
    Microservice();

    /**
     * @brief Destroy the Microservice object
     */
    ~Microservice();

    /**
     * @brief Initialize the microservice
     * 
     * @return true if initialization was successful
     * @return false if initialization failed
     */
    bool initialize();

    /**
     * @brief Run the microservice
     * 
     * @return int exit code
     */
    int run();

    /**
     * @brief Shutdown the microservice gracefully
     */
    void shutdown();

private:
    // Private members
    std::unique_ptr<HttpServer> server_;
    std::unique_ptr<Database> db_;
    std::map<std::string, std::string> config_;
    
    /**
     * @brief Load configuration from .env file
     * 
     * @return true if loading was successful
     * @return false if loading failed
     */
    bool loadConfig();
    
    /**
     * @brief Setup signal handlers for graceful shutdown
     */
    void setupSignalHandlers();
};

#endif // MICROSERVICE_H