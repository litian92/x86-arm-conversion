cmake_minimum_required(VERSION 3.16)
project(vec_dot LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable(vec_dot
  src/main.cpp
  src/dot_product.cpp
  src/x86_simd.cpp
)

target_include_directories(vec_dot PRIVATE include)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|i686")
  target_compile_options(vec_dot PRIVATE -mavx2 -mfma)
  target_compile_definitions(vec_dot PRIVATE VEC_DOT_ENABLE_X86_SIMD=1)
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|ARM64")
  target_compile_options(vec_dot PRIVATE -march=armv8-a+simd)
  target_compile_definitions(vec_dot PRIVATE VEC_DOT_ENABLE_ARM_NEON=1)
endif()

enable_testing()
add_test(NAME vec_dot_smoke COMMAND vec_dot --self-test)
