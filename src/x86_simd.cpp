#include "dot_product.h"

// This file intentionally contains x86-specific patterns so migrate-ease can
// demonstrate migration feedback. The Arm build skips the AVX2 block at
// compile time, but the scanner still flags the intrinsics for review.

#if defined(__x86_64__) || defined(_M_X64)
#include <immintrin.h>

double dot_product_simd(const double* a, const double* b, std::size_t n) {
  __m256d sum = _mm256_setzero_pd();
  std::size_t i = 0;

  for (; i + 4 <= n; i += 4) {
    __m256d va = _mm256_loadu_pd(a + i);
    __m256d vb = _mm256_loadu_pd(b + i);
    sum = _mm256_fmadd_pd(va, vb, sum);
  }

  alignas(32) double partial[4];
  _mm256_storeu_pd(partial, sum);
  double total = partial[0] + partial[1] + partial[2] + partial[3];
  for (; i < n; ++i) {
    total += a[i] * b[i];
  }
  return total;
}

#elif defined(__aarch64__)
#include <arm_neon.h>

double dot_product_simd(const double* a, const double* b, std::size_t n) {
  float64x2_t sum = vdupq_n_f64(0.0);
  std::size_t i = 0;

  for (; i + 2 <= n; i += 2) {
    float64x2_t va = vld1q_f64(a + i);
    float64x2_t vb = vld1q_f64(b + i);
    sum = vfmaq_f64(sum, va, vb);
  }

  double total = vgetq_lane_f64(sum, 0) + vgetq_lane_f64(sum, 1);
  for (; i < n; ++i) {
    total += a[i] * b[i];
  }
  return total;
}

#else
double dot_product_simd(const double* a, const double* b, std::size_t n) {
  return dot_product_scalar(a, b, n);
}
#endif
