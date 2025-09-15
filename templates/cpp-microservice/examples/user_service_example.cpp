#include "microservice.h"
#include "user_model.h"
#include <iostream>

int main(int argc, char* argv[]) {
    Microservice service;
    
    if (!service.initialize()) {
        std::cerr << "Failed to initialize microservice" << std::endl;
        return 1;
    }
    
    // Example of using the user model
    UserModel user(1, "John Doe", "john@example.com");
    std::cout << "User: " << user.getName() << " (" << user.getEmail() << ")" << std::endl;
    
    // Save the user
    if (user.save()) {
        std::cout << "User saved successfully" << std::endl;
    } else {
        std::cerr << "Failed to save user" << std::endl;
    }
    
    // Find a user by ID
    UserModel foundUser = UserModel::findById(1);
    if (foundUser.getId() != 0) {
        std::cout << "Found user: " << foundUser.getName() << " (" << foundUser.getEmail() << ")" << std::endl;
    } else {
        std::cout << "User not found" << std::endl;
    }
    
    // Find all users
    std::vector<UserModel> users = UserModel::findAll();
    std::cout << "Found " << users.size() << " users:" << std::endl;
    for (const auto& u : users) {
        std::cout << "  - " << u.getName() << " (" << u.getEmail() << ")" << std::endl;
    }
    
    return service.run();
}