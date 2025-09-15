# C++ Microservice Template

This documentation explains how to use the C++ microservice template to create new services quickly and efficiently.

## Overview

The C++ microservice template provides a standardized structure and set of tools for creating new microservices in C++. It includes:

- A simple Makefile-based build system
- Docker support for containerization
- Configuration management with .env files
- Basic HTTP server framework
- Database wrapper interface
- Unit testing with Google Test
- Clean, modular code organization

## Directory Structure

```
templates/cpp-microservice/
├── src/              # Source code files
├── include/          # Header files
├── tests/            # Unit tests
├── config/           # Configuration files
├── examples/         # Example implementations
├── docs/             # Documentation files
├── scripts/          # Utility scripts
├── Makefile          # Build system
├── Dockerfile        # Container definition
├── .env              # Environment variables
└── README.md         # Template documentation
```

## Creating a New C++ Microservice

To create a new C++ microservice from the template, use the provided script:

```bash
./scripts/init_cpp_service.sh <service-name>
```

For example:
```bash
./scripts/init_cpp_service.sh user-service
```

This will create a new directory in `services/` with all the necessary files copied from the template.

## Building and Running

### Prerequisites

Before building, ensure you have the required dependencies installed:

```bash
# Install dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y build-essential libgtest-dev libcurl4-openssl-dev libssl-dev

# Or use the provided make target
make install-deps
```

### Building

To build the microservice, navigate to the service directory and run:

```bash
# Build the service
make

# Build and run tests
make run-tests

# Clean build artifacts
make clean
```

### Running

After building, you can run the microservice:

```bash
# Run the service
./build/<service-name>
```

### Docker

The template includes a Dockerfile for containerization:

```bash
# Build Docker image
docker build -t <service-name> .

# Run container
docker run -p 8080:8080 <service-name>
```

## Configuration

The microservice uses a `.env` file for configuration. Copy the provided `.env` file and modify as needed:

```env
# Server Configuration
HOST=0.0.0.0
PORT=8080

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=microservice
DB_USER=microservice
DB_PASS=password

# Logging
LOG_LEVEL=info
LOG_FILE=/var/log/microservice.log

# Feature Flags
ENABLE_FEATURE_X=true
```

Access configuration values in your code using the ConfigManager class:

```cpp
#include "config_manager.h"

ConfigManager config;
config.load(".env");

std::string host = config.get("HOST", "0.0.0.0");
int port = config.getInt("PORT", 8080);
bool enableFeature = config.getBool("ENABLE_FEATURE_X", false);
```

## Adding New Features

### Creating a New Model

1. Create a new header file in `include/` (e.g., `user_model.h`)
2. Create a corresponding implementation file in `src/` (e.g., `user_model.cpp`)
3. Include the header in your main code and use the model

### Adding Routes

Register new routes with the HTTP server in your main code:

```cpp
#include "http_server.h"

// In your service initialization
server->get("/users", [](const std::map<std::string, std::string>& params) -> std::string {
    // Handle GET /users request
    return "User list";
});

server->post("/users", [](const std::map<std::string, std::string>& params) -> std::string {
    // Handle POST /users request
    return "User created";
});
```

### Adding Database Operations

Use the provided Database wrapper to perform database operations:

```cpp
#include "database.h"

Database db;
db.connect("localhost", 5432, "mydb", "user", "password");
auto results = db.query("SELECT * FROM users");
```

## Testing

Unit tests are written using Google Test. Add new tests to the `tests/` directory and update the test make target as needed.

```bash
# Run tests
make run-tests
```

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

## Best Practices

1. **Modular Design**: Keep your code organized in separate files for each class/component
2. **Configuration**: Use the `.env` file for all configuration values
3. **Error Handling**: Implement proper error handling and logging
4. **Testing**: Write unit tests for your models and business logic
5. **Documentation**: Document your code with comments and update this guide as needed

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

## Contributing

To contribute to the template itself:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License.