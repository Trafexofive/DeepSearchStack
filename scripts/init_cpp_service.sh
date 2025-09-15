#!/bin/bash

# Script to initialize a new C++ microservice from the template

# Check if a service name was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <service-name>"
    echo "Example: $0 user-service"
    exit 1
fi

SERVICE_NAME=$1
TEMPLATE_DIR="/home/mlamkadm/services/deeps/templates/cpp-microservice"
TARGET_DIR="/home/mlamkadm/services/deeps/services/$SERVICE_NAME"

# Check if the template directory exists
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "Error: Template directory not found: $TEMPLATE_DIR"
    exit 1
fi

# Check if the target directory already exists
if [ -d "$TARGET_DIR" ]; then
    echo "Error: Target directory already exists: $TARGET_DIR"
    exit 1
fi

# Create the target directory
echo "Creating new C++ microservice: $SERVICE_NAME"
mkdir -p "$TARGET_DIR"

# Copy template files to the target directory
cp -r "$TEMPLATE_DIR"/* "$TARGET_DIR"/

# Update the service name in relevant files
sed -i "s/microservice/$SERVICE_NAME/g" "$TARGET_DIR/Makefile"
sed -i "s/Microservice/${SERVICE_NAME^}/g" "$TARGET_DIR/Makefile"

# Create a simple main file for the new service
cat > "$TARGET_DIR/src/main.cpp" << EOF
#include "microservice.h"
#include <iostream>

int main(int argc, char* argv[]) {
    Microservice service;
    
    if (!service.initialize()) {
        std::cerr << "Failed to initialize $SERVICE_NAME" << std::endl;
        return 1;
    }
    
    std::cout << "$SERVICE_NAME initialized successfully" << std::endl;
    
    return service.run();
}
EOF

# Create a README for the new service
cat > "$TARGET_DIR/README.md" << EOF
# $SERVICE_NAME

This is a C++ microservice for $SERVICE_NAME, built using the C++ microservice template.

## Features

- RESTful API
- Configuration management
- Docker support
- Unit testing
- Health checks

## Getting Started

### Prerequisites

- GCC or Clang compiler with C++17 support
- GNU Make
- Docker (for containerization)

### Building

\`\`\`bash
# Build the service
make

# Build and run tests
make run-tests

# Clean build artifacts
make clean
\`\`\`

### Running

\`\`\`bash
# Run the service
./build/$SERVICE_NAME

# Run with Docker
docker build -t $SERVICE_NAME .
docker run -p 8080:8080 $SERVICE_NAME
\`\`\`

## Configuration

The service uses a \`.env\` file for configuration. Copy the provided \`.env\` file and modify as needed.

## API Endpoints

- \`GET /health\` - Health check endpoint
- \`GET /version\` - Version information

## Development

### Adding New Features

1. Add new header files to the \`include/\` directory
2. Add new implementation files to the \`src/\` directory
3. Update the Makefile if needed
4. Add tests to the \`tests/\` directory

### Testing

Unit tests are written using Google Test. Add new tests to the \`tests/\` directory.

\`\`\`bash
# Run tests
make run-tests
\`\`\`

## Deployment

The service can be deployed using Docker:

\`\`\`bash
docker build -t $SERVICE_NAME .
docker run -d -p 8080:8080 --name $SERVICE_NAME $SERVICE_NAME
\`\`\`
EOF

echo "New C++ microservice '$SERVICE_NAME' created successfully at $TARGET_DIR"
echo "To get started:"
echo "  cd $TARGET_DIR"
echo "  make"
echo "  ./build/$SERVICE_NAME"