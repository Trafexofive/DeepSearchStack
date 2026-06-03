cmake_minimum_required(VERSION 3.14)
project(dss-sdk VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(dss-sdk INTERFACE)
target_include_directories(dss-sdk INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})

find_package(CURL REQUIRED)
target_link_libraries(dss-sdk INTERFACE CURL::libcurl)

option(DSS_BUILD_TESTS "Build tests" ON)
if(DSS_BUILD_TESTS)
    add_subdirectory(tests)
endif()
