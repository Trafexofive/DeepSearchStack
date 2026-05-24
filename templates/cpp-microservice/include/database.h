#ifndef DATABASE_H
#define DATABASE_H

#include <string>
#include <vector>
#include <map>

/**
 * @brief Simple database wrapper class
 * 
 * This class provides a basic interface for database operations.
 */
class Database {
public:
    /**
     * @brief Construct a new Database object
     */
    Database();
    
    /**
     * @brief Destroy the Database object
     */
    ~Database();
    
    /**
     * @brief Connect to the database
     * 
     * @param host Database host
     * @param port Database port
     * @param dbname Database name
     * @param user Username
     * @param password Password
     * @return true if connection was successful
     * @return false if connection failed
     */
    bool connect(const std::string& host, int port, const std::string& dbname, 
                 const std::string& user, const std::string& password);
    
    /**
     * @brief Disconnect from the database
     */
    void disconnect();
    
    /**
     * @brief Execute a query and return results
     * 
     * @param query SQL query to execute
     * @return std::vector<std::map<std::string, std::string>> Results as key-value pairs
     */
    std::vector<std::map<std::string, std::string>> query(const std::string& query);
    
    /**
     * @brief Execute a non-query statement (INSERT, UPDATE, DELETE)
     * 
     * @param statement SQL statement to execute
     * @return true if execution was successful
     * @return false if execution failed
     */
    bool execute(const std::string& statement);

private:
    bool connected_;
    std::string connection_string_;
};

#endif // DATABASE_H