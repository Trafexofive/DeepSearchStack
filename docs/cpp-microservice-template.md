# C++ Microservice Template Guide

This guide explains how to use the C++ microservice template to create new services quickly and efficiently.

## Getting Started

1. Copy the template directory to your new service location:
   ```
   cp -r templates/cpp-microservice services/my-new-service
   cd services/my-new-service
   ```

2. Modify the `.env` file to configure your service:
   ```
   # Server Configuration
   HOST=0.0.0.0
   PORT=8080
   
   # Add your custom configuration values here
   MY_SERVICE_API_KEY=your_secret_key
   ```

3. Build the service:
   ```
   make
   ```

4. Run the service:
   ```
   ./build/microservice
   ```

## Adding New Features

### 1. Creating a New Model

Create a new header file in `include/`:
```cpp
// include/product_model.h
#ifndef PRODUCT_MODEL_H
#define PRODUCT_MODEL_H

#include <string>

class ProductModel {
public:
    ProductModel(int id, const std::string& name, double price);
    
    int getId() const;
    std::string getName() const;
    double getPrice() const;
    
private:
    int id_;
    std::string name_;
    double price_;
};

#endif // PRODUCT_MODEL_H
```

Create the implementation in `src/`:
```cpp
// src/product_model.cpp
#include "product_model.h"

ProductModel::ProductModel(int id, const std::string& name, double price)
    : id_(id), name_(name), price_(price) {}

int ProductModel::getId() const { return id_; }
std::string ProductModel::getName() const { return name_; }
double ProductModel::getPrice() const { return price_; }
```

### 2. Adding a New Endpoint

Modify your main service file to register new routes:
```cpp
// In your main service initialization
server_->get("/products", [this](const std::map<std::string, std::string>& params) -> std::string {
    // Handle GET /products request
    return "{\"products\": []}";
});

server_->post("/products", [this](const std::map<std::string, std::string>& params) -> std::string {
    // Handle POST /products request
    return "{\"message\": \"Product created\"}";
});
```

### 3. Adding Database Operations

Use the provided Database wrapper:
```cpp
// In your service implementation
Database db;
db.connect("localhost", 5432, "mydb", "user", "password");

// Query data
auto results = db.query("SELECT * FROM products");

// Insert data
bool success = db.execute("INSERT INTO products (name, price) VALUES ('Product 1', 19.99)");
```

## Building and Testing

### Build Commands

```bash
# Build the service
make

# Build with debug symbols
make debug

# Clean build artifacts
make clean

# Run tests
make test

# Format code
make format
```

### Docker Support

The template includes a Dockerfile for containerization:
```bash
# Build Docker image
docker build -t my-service .

# Run container
docker run -p 8080:8080 my-service
```

## Configuration Management

The service uses a `.env` file for configuration:
```env
# Server settings
HOST=0.0.0.0
PORT=8080

# Database settings
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=myuser
DB_PASS=mypass

# Feature flags
ENABLE_CACHE=true
CACHE_TTL=3600
```

Access configuration values in your code:
```cpp
std::string host = configManager.get("HOST", "0.0.0.0");
int port = configManager.getInt("PORT", 8080);
bool enableCache = configManager.getBool("ENABLE_CACHE", false);
```

## Best Practices

1. **Modular Design**: Keep your code organized in separate files for each class/component
2. **Configuration**: Use the `.env` file for all configuration values
3. **Error Handling**: Implement proper error handling and logging
4. **Testing**: Write unit tests for your models and business logic
5. **Documentation**: Document your code with comments and update this guide as needed

## Extending the Template

### Adding New Dependencies

1. Add new dependencies to the Dockerfile:
   ```dockerfile
   RUN apt-get update && apt-get install -y \
       libmylib-dev \
       && rm -rf /var/lib/apt/lists/*
   ```

2. Update the Makefile if needed:
   ```makefile
   LIBS = -lpthread -lmylib
   ```

### Adding New Libraries

For third-party libraries, you can either:
1. Install them via the system package manager (preferred)
2. Include them as submodules in your repository
3. Use a package manager like Conan or vcpkg

## Troubleshooting

### Common Issues

1. **Build Failures**: Ensure all dependencies are installed:
   ```bash
   make install-deps
   ```

2. **Runtime Errors**: Check the logs and configuration:
   ```bash
   cat /var/log/microservice.log
   ```

3. **Docker Issues**: Verify Docker is running and you have permissions:
   ```bash
   sudo systemctl status docker
   sudo usermod -aG docker $USER
   ```

### Getting Help

If you encounter issues:
1. Check the logs for error messages
2. Verify your configuration in the `.env` file
3. Ensure all dependencies are properly installed
4. Consult the documentation for any third-party libraries used
```