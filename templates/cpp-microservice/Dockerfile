# Dockerfile for C++ Microservice

FROM ubuntu:22.04

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libgtest-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    clang-format \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

# Build the microservice
RUN make

# Expose port
EXPOSE 8080

# Command to run the microservice
CMD [\"./build/microservice\"]