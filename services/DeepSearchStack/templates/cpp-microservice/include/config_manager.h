#ifndef CONFIG_MANAGER_H
#define CONFIG_MANAGER_H

#include <string>
#include <map>

/**
 * @brief Configuration manager class
 * 
 * This class handles loading and accessing configuration values from environment variables and .env files.
 */
class ConfigManager {
public:
    /**
     * @brief Construct a new Config Manager object
     */
    ConfigManager();
    
    /**
     * @brief Destroy the Config Manager object
     */
    ~ConfigManager();
    
    /**
     * @brief Load configuration from .env file and environment variables
     * 
     * @param envFile Path to the .env file
     * @return true if loading was successful
     * @return false if loading failed
     */
    bool load(const std::string& envFile = ".env");
    
    /**
     * @brief Get a configuration value by key
     * 
     * @param key Configuration key
     * @param defaultValue Default value if key is not found
     * @return std::string Configuration value or default value
     */
    std::string get(const std::string& key, const std::string& defaultValue = "") const;
    
    /**
     * @brief Get an integer configuration value by key
     * 
     * @param key Configuration key
     * @param defaultValue Default value if key is not found or conversion fails
     * @return int Configuration value or default value
     */
    int getInt(const std::string& key, int defaultValue = 0) const;
    
    /**
     * @brief Get a boolean configuration value by key
     * 
     * @param key Configuration key
     * @param defaultValue Default value if key is not found or conversion fails
     * @return true Configuration value is true-like or default value is true
     * @return false Configuration value is false-like or default value is false
     */
    bool getBool(const std::string& key, bool defaultValue = false) const;

private:
    std::map<std::string, std::string> config_;
    
    /**
     * @brief Parse a line from the .env file
     * 
     * @param line Line to parse
     */
    void parseLine(const std::string& line);
    
    /**
     * @brief Trim whitespace from both ends of a string
     * 
     * @param str String to trim
     * @return std::string Trimmed string
     */
    std::string trim(const std::string& str) const;
};

#endif // CONFIG_MANAGER_H