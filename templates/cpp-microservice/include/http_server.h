#ifndef HTTP_SERVER_H
#define HTTP_SERVER_H

#include <string>
#include <functional>
#include <map>
#include <vector>

// Forward declaration
class Microservice;

/**
 * @brief Simple HTTP server class
 * 
 * This class provides a basic HTTP server implementation for the microservice.
 */
class HttpServer {
public:
    // Type aliases for request handlers
    using RequestHandler = std::function<std::string(const std::map<std::string, std::string>& params)>;
    
    /**
     * @brief Construct a new HttpServer object
     * 
     * @param service Reference to the parent microservice
     */
    HttpServer(Microservice& service);
    
    /**
     * @brief Destroy the HttpServer object
     */
    ~HttpServer();
    
    /**
     * @brief Start the HTTP server
     * 
     * @param host Host address to bind to
     * @param port Port to listen on
     * @return true if server started successfully
     * @return false if server failed to start
     */
    bool start(const std::string& host, int port);
    
    /**
     * @brief Stop the HTTP server
     */
    void stop();
    
    /**
     * @brief Register a GET route
     * 
     * @param path Route path
     * @param handler Handler function
     */
    void get(const std::string& path, const RequestHandler& handler);
    
    /**
     * @brief Register a POST route
     * 
     * @param path Route path
     * @param handler Handler function
     */
    void post(const std::string& path, const RequestHandler& handler);

private:
    Microservice& service_;
    bool running_;
    
    // Route handlers
    std::map<std::string, RequestHandler> get_handlers_;
    std::map<std::string, RequestHandler> post_handlers_;
};

#endif // HTTP_SERVER_H