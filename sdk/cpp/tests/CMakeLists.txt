cmake_minimum_required(VERSION 3.14)
project(dss-sdk-tests LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(dss-sdk-tests test_dss.cpp)
target_include_directories(dss-sdk-tests PRIVATE ..)
find_package(CURL REQUIRED)
target_link_libraries(dss-sdk-tests PRIVATE CURL::libcurl)
