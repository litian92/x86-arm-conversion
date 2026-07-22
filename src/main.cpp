#include "dot_product.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

bool run_self_test() {
  const std::vector<double> a{1.0, 2.0, 3.0, 4.0, 5.0, 6.0};
  const std::vector<double> b{6.0, 5.0, 4.0, 3.0, 2.0, 1.0};

  const double expected = dot_product_scalar(a.data(), b.data(), a.size());
  const double actual = dot_product(a, b);

  if (std::abs(expected - actual) > 1e-9) {
    std::cerr << "self-test failed: expected " << expected << ", got " << actual << '\n';
    return false;
  }
  return true;
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc > 1 && std::string(argv[1]) == "--self-test") {
    return run_self_test() ? EXIT_SUCCESS : EXIT_FAILURE;
  }

  const std::vector<double> a{1.0, 2.0, 3.0, 4.0};
  const std::vector<double> b{4.0, 3.0, 2.0, 1.0};
  const double result = dot_product(a, b);

  std::cout << "vec_dot result=" << result << '\n';

#if defined(VEC_DOT_ENABLE_X86_SIMD)
  std::cout << "backend=x86_avx2\n";
#elif defined(VEC_DOT_ENABLE_ARM_NEON)
  std::cout << "backend=arm_neon\n";
#else
  std::cout << "backend=scalar\n";
#endif

  return run_self_test() ? EXIT_SUCCESS : EXIT_FAILURE;
}
