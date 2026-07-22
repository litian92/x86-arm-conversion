#pragma once

#include <cstddef>
#include <vector>

// Portable baseline dot product.
double dot_product_scalar(const double* a, const double* b, std::size_t n);

// Architecture-specific fast path (x86 AVX2 or Arm NEON when available).
double dot_product_simd(const double* a, const double* b, std::size_t n);

// Convenience wrapper used by the demo program.
double dot_product(const std::vector<double>& a, const std::vector<double>& b);
