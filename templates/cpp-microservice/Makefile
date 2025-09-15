# Makefile for C++ Microservice

# Compiler and flags
CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -O2 -g
INCLUDES = -I./include
LIBS = -lpthread

# Directories
SRC_DIR = src
INCLUDE_DIR = include
BUILD_DIR = build
TEST_DIR = tests

# Files
SRCS = $(wildcard $(SRC_DIR)/*.cpp)
OBJS = $(SRCS:$(SRC_DIR)/%.cpp=$(BUILD_DIR)/%.o)
TARGET = $(BUILD_DIR)/microservice

TEST_SRCS = $(wildcard $(TEST_DIR)/*.cpp)
TEST_TARGET = $(BUILD_DIR)/test_microservice

# Default target
all: $(TARGET)

# Create build directory
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Build the main executable
$(TARGET): $(OBJS) | $(BUILD_DIR)
	$(CXX) $(OBJS) -o $@ $(LIBS)

# Compile source files
$(BUILD_DIR)/%.o: $(SRC_DIR)/%.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

# Build tests
test: $(TEST_TARGET)

$(TEST_TARGET): $(TEST_SRCS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< -o $@ $(LIBS) -lgtest -lgtest_main

# Run tests
run-tests: test
	$(TEST_TARGET)

# Clean build artifacts
clean:
	rm -rf $(BUILD_DIR)

# Install dependencies (Ubuntu/Debian)
install-deps:
	sudo apt-get update
	sudo apt-get install -y build-essential libgtest-dev libcurl4-openssl-dev libssl-dev

# Format code
format:
	find $(SRC_DIR) $(INCLUDE_DIR) $(TEST_DIR) -name "*.cpp" -o -name "*.hpp" | xargs clang-format -i

# Help
help:
	@echo "Available targets:"
	@echo "  all          - Build the microservice (default)"
	@echo "  test         - Build tests"
	@echo "  run-tests    - Build and run tests"
	@echo "  clean        - Remove build artifacts"
	@echo "  install-deps - Install required dependencies (Ubuntu/Debian)"
	@echo "  format       - Format code with clang-format"
	@echo "  help         - Show this help message"

.PHONY: all test run-tests clean install-deps format help