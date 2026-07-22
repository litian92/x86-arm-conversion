# Sample container for check_image / skopeo Arm64 verification in CI.
FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j"$(nproc)"

FROM debian:bookworm-slim
COPY --from=build /src/build/vec_dot /usr/local/bin/vec_dot
ENTRYPOINT ["vec_dot", "--self-test"]
