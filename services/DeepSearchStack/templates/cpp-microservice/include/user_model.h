#ifndef USER_MODEL_H
#define USER_MODEL_H

#include <string>
#include <vector>

/**
 * @brief User model class
 * 
 * This class represents a user in the system.
 */
class UserModel {
public:
    /**
     * @brief Construct a new User Model object
     */
    UserModel();
    
    /**
     * @brief Construct a new User Model object with parameters
     * 
     * @param id User ID
     * @param name User name
     * @param email User email
     */
    UserModel(int id, const std::string& name, const std::string& email);
    
    /**
     * @brief Destroy the User Model object
     */
    ~UserModel();
    
    // Getters
    int getId() const;
    std::string getName() const;
    std::string getEmail() const;
    
    // Setters
    void setId(int id);
    void setName(const std::string& name);
    void setEmail(const std::string& email);
    
    /**
     * @brief Save the user to the database
     * 
     * @return true if save was successful
     * @return false if save failed
     */
    bool save();
    
    /**
     * @brief Find a user by ID
     * 
     * @param id User ID to find
     * @return UserModel User object if found, empty object if not found
     */
    static UserModel findById(int id);
    
    /**
     * @brief Find all users
     * 
     * @return std::vector<UserModel> List of all users
     */
    static std::vector<UserModel> findAll();

private:
    int id_;
    std::string name_;
    std::string email_;
};

#endif // USER_MODEL_H