cmake_minimum_required(VERSION 3.14)
project(cpp_microservice VERSION 1.0.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Set default build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Include custom CMake modules
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# Enable testing
enable_testing()

# Find required packages
find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)

# Options
option(ENABLE_TESTS "Enable tests" ON)
option(ENABLE_EXAMPLES "Enable examples" ON)
option(BUILD_SHARED_LIBS "Build shared libraries" OFF)

# Compiler flags
if(MSVC)
    add_compile_options(/W4)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Include subdirectories
add_subdirectory(src)

if(ENABLE_TESTS)
    add_subdirectory(tests)
endif()

if(ENABLE_EXAMPLES)
    add_subdirectory(examples)
endif()

# Install documentation
install(DIRECTORY docs/ DESTINATION share/doc/${PROJECT_NAME})

# CPack configuration for packaging
set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)