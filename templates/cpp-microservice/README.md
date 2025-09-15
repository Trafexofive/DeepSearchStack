# C++ Microservice Template

This is a boilerplate template for creating C++ microservices. It provides a scalable, organized structure that makes it easy to add new models, features, and functionality.

## Features

- Simple Makefile-based build system
- Docker support for containerization
- Configuration management with .env files
- Basic HTTP server framework
- Database wrapper interface
- Unit testing with Google Test
- Clean, modular code organization

## Directory Structure

```
cpp-microservice/
├── src/              # Source code files
├── include/          # Header files
├── tests/            # Unit tests
├── config/           # Configuration files
├── Makefile          # Build system
├── Dockerfile        # Container definition
├── .env              # Environment variables
└── README.md         # This file
```

## Getting Started

### Prerequisites

- GCC or Clang compiler with C++17 support
- GNU Make
- Docker (for containerization)

### Building

```bash
# Build the microservice
make

# Build and run tests
make run-tests

# Clean build artifacts
make clean

# Install dependencies (Ubuntu/Debian)
make install-deps
```

### Running

```bash
# Run the microservice
./build/microservice

# Run with Docker
docker build -t my-microservice .
docker run -p 8080:8080 my-microservice
```

## Adding New Features

1. Add new header files to the `include/` directory
2. Add new implementation files to the `src/` directory
3. Update the Makefile if needed
4. Add tests to the `tests/` directory

## Configuration

The microservice uses a `.env` file for configuration. Copy the provided `.env.example` to `.env` and modify as needed.

## API Endpoints

By default, the microservice exposes the following endpoints:

- `GET /health` - Health check endpoint
- `GET /version` - Version information

Additional endpoints can be added by registering routes with the HTTP server.

## Extending the Microservice

### Adding Models

1. Create a new header file in `include/` (e.g., `user_model.h`)
2. Create a corresponding implementation file in `src/` (e.g., `user_model.cpp`)
3. Include the header in your main code and use the model

### Adding Routes

In your main code, register new routes with the HTTP server:

```cpp
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

## Deployment

The microservice can be deployed using Docker:

```bash
docker build -t my-microservice .
docker run -d -p 8080:8080 --name my-microservice my-microservice
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License.