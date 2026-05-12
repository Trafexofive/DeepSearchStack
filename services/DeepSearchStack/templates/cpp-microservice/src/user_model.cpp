#include "user_model.h"
#include <iostream>

UserModel::UserModel() : id_(0) {
    // Default constructor
}

UserModel::UserModel(int id, const std::string& name, const std::string& email) 
    : id_(id), name_(name), email_(email) {
    // Parameterized constructor
}

UserModel::~UserModel() {
    // Destructor
}

// Getters
int UserModel::getId() const {
    return id_;
}

std::string UserModel::getName() const {
    return name_;
}

std::string UserModel::getEmail() const {
    return email_;
}

// Setters
void UserModel::setId(int id) {
    id_ = id;
}

void UserModel::setName(const std::string& name) {
    name_ = name;
}

void UserModel::setEmail(const std::string& email) {
    email_ = email;
}

bool UserModel::save() {
    std::cout << "Saving user: " << name_ << " (" << email_ << ")" << std::endl;
    
    // In a real implementation, you would save to the database here
    // For now, we'll just return true to indicate success
    
    return true;
}

UserModel UserModel::findById(int id) {
    std::cout << "Finding user by ID: " << id << std::endl;
    
    // In a real implementation, you would query the database here
    // For now, we'll return a dummy user
    
    if (id == 1) {
        return UserModel(1, "John Doe", "john@example.com");
    }
    
    return UserModel(); // Return empty user if not found
}

std::vector<UserModel> UserModel::findAll() {
    std::cout << "Finding all users" << std::endl;
    
    // In a real implementation, you would query the database here
    // For now, we'll return a dummy list of users
    
    std::vector<UserModel> users;
    users.emplace_back(1, "John Doe", "john@example.com");
    users.emplace_back(2, "Jane Smith", "jane@example.com");
    
    return users;
}