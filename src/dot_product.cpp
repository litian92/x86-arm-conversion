#include "dot_product.h"

#include <cmath>
#include <stdexcept>

double dot_product_scalar(const double* a, const double* b, std::size_t n) {
  double sum = 0.0;
  for (std::size_t i = 0; i < n; ++i) {
    sum += a[i] * b[i];
  }
  return sum;
}

double dot_product(const std::vector<double>& a, const std::vector<double>& b) {
  if (a.size() != b.size()) {
    throw std::invalid_argument("vector sizes must match");
  }
  if (a.empty()) {
    return 0.0;
  }
  return dot_product_simd(a.data(), b.data(), a.size());
}
