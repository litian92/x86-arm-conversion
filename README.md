# ARM MCP Cross-Architecture CI

GitHub Actions workflow that verifies your repository builds on **x86_64** and **arm64**, runs [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server) analysis inside a container, and posts actionable feedback on pull requests.

## What it does

| Job | Purpose |
| --- | --- |
| **Detect project** | Finds languages, Dockerfiles, and container base images |
| **Build (matrix)** | Compiles on `ubuntu-latest` (x86_64) and `ubuntu-24.04-arm` (arm64) |
| **ARM MCP analysis** | Runs Arm MCP tools via `armlimited/arm-mcp` Docker image |
| **Post PR feedback** | Updates a single PR comment with build status and optimization guidance |

### Arm MCP tools used

- **`migrate_ease_scan`** — scans C/C++, Python, Go, JavaScript, and Java for x86-specific code and migration blockers
- **`check_image`** / **`skopeo`** — verifies container images support arm64
- **`knowledge_base_search`** — pulls Arm optimization and migration guidance
- **`mca`** — LLVM Machine Code Analyzer on object/assembly files when build artifacts exist

## Sample project: `vec_dot`

This repository includes a minimal C++ dot-product demo that exercises the full pipeline:

| Component | Purpose |
| --- | --- |
| `CMakeLists.txt` | Cross-arch build (AVX2 on x86_64, NEON on arm64) |
| `src/x86_simd.cpp` | x86 intrinsics (`immintrin.h`, `_mm256_*`) for **migrate-ease** findings |
| `src/main.cpp` | Runnable demo + `--self-test` used by CTest |
| `Dockerfile` | Multi-stage image for **check_image** / **skopeo** |
| `.arm-mcp-ci.yaml` | Pins `cpp` scans and CMake build commands |

### Build locally

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
ctest --test-dir build --output-on-failure
./build/vec_dot
```

On Windows with Visual Studio Build Tools, use `-G "Visual Studio 17 2022"` or Ninja if installed.

## Quick start

1. Copy this repository's CI files into your project (or use this repo as a template):

   ```
   .github/workflows/arm-mcp-ci.yml
   ci/
   .arm-mcp-ci.yaml.example
   ```

2. Optionally create `.arm-mcp-ci.yaml` from the example to customize languages and build commands.

3. Open a pull request — the workflow runs automatically and posts a comment like:

   > **Overall:** needs attention  
   > x86_64 build: success | arm64 build: failure  
   > migrate-ease findings + performance suggestions

## Configuration

Create `.arm-mcp-ci.yaml` in the repository root:

```yaml
languages:
  - cpp
  - go

build:
  x86_64: cmake -S . -B build && cmake --build build
  arm64: cmake -S . -B build && cmake --build build

docker_images:
  - myorg/myapp:latest
```

When `build` commands are omitted, the workflow auto-detects common systems (Make, CMake, Go, Cargo, npm, Python, Dockerfile).

## Local testing

### Detect project metadata

```bash
pip install -r ci/requirements.txt
python ci/detect_project.py --json
```

### Run a local build

```bash
bash ci/build_project.sh x86_64
bash ci/build_project.sh arm64   # on an Arm machine or GitHub arm64 runner
```

### Run Arm MCP analysis (requires Docker)

```bash
docker pull armlimited/arm-mcp:latest
export LANGUAGES='["cpp"]'
export DOCKER_IMAGES='["nginx:latest"]'
python ci/run_analysis.py
cat ci-output/report.md
```

## Requirements

- **GitHub Actions** with `ubuntu-24.04-arm` runners enabled (public repos include Arm runners; org policies may vary)
- **Docker** on the analysis job runner (provided on `ubuntu-latest` GitHub-hosted runners)
- **`armlimited/arm-mcp`** image pulled at runtime (no API keys required for core tools)

## Optional: Arm Performix profiling

The **`apx_recipe_run`** tool (code hotspots, instruction mix) requires SSH access to a target machine with PMU counters. This is not enabled by default in CI because it needs:

- SSH private key and `known_hosts` mounted into the Arm MCP container
- A reachable Arm64 host to profile

To extend the workflow for Performix, add secrets and volume mounts following the [Arm MCP Server docs](https://github.com/arm/mcp#quick-start), then call `apx_recipe_run` from `ci/run_analysis.py`.

## Workflow permissions

The workflow requests `pull-requests: write` so it can create/update PR comments. `GITHUB_TOKEN` is used automatically — no extra secrets are required for commenting.

## Troubleshooting

| Issue | Fix |
| --- | --- |
| migrate-ease scan times out | Increase `timeout-minutes` on the analysis job; large repos may need 30+ minutes |
| Empty `/workspace` in scan results | Ensure the checkout step runs before analysis and Docker volume mount path is correct |
| arm64 runner unavailable | Confirm your org allows `ubuntu-24.04-arm`; use a self-hosted Arm runner and update `runs-on` |
| Build not detected | Add explicit `build:` commands in `.arm-mcp-ci.yaml` |

## References

- [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server)
- [arm/mcp on GitHub](https://github.com/arm/mcp)
- [Automate x86 to Arm migration with GitHub Copilot](https://learn.arm.com/learning-paths/servers-and-cloud-computing/docker-mcp-toolkit/4-run-migration/)

## License

Apache-2.0 (same as Arm MCP Server)
