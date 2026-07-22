# ARM MCP Analysis CI

GitHub Actions workflow that runs [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server) analysis inside a container and posts actionable feedback on pull requests.

## What it does

| Job | Purpose |
| --- | --- |
| **Detect project** | Finds languages, Dockerfiles, and container base images |
| **ARM MCP analysis** | Runs Arm MCP tools via `armlimited/arm-mcp` Docker image |
| **Post PR feedback** | Summary comment plus inline review suggestions with **Apply suggestion** buttons |

Inline suggestions use GitHub's ` ```suggestion ` blocks on the PR diff so reviewers can apply fixes from the **Files changed** tab.

### Arm MCP tools used

- **`migrate_ease_scan`** — scans C/C++, Python, Go, JavaScript, and Java for x86-specific code and migration blockers
- **`check_image`** / **`skopeo`** — verifies container images support arm64
- **`knowledge_base_search`** — pulls Arm optimization and migration guidance
- **`mca`** — LLVM Machine Code Analyzer on object/assembly files when build artifacts exist in the repo

## Sample project: `vec_dot`

This repository includes a minimal C++ dot-product demo for local testing and migrate-ease findings:

| Component | Purpose |
| --- | --- |
| `CMakeLists.txt` | Cross-arch build (AVX2 on x86_64, NEON on arm64) |
| `src/x86_simd.cpp` | x86 intrinsics (`immintrin.h`, `_mm256_*`) for **migrate-ease** findings |
| `src/main.cpp` | Runnable demo + `--self-test` used by CTest |
| `Dockerfile` | Multi-stage image for **check_image** / **skopeo** |
| `.arm-mcp-ci.yaml` | Pins `cpp` scans and Docker images to inspect |

### Build locally (optional)

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
ctest --test-dir build --output-on-failure
./build/vec_dot
```

Building locally is optional; CI only runs Arm MCP analysis.

## Quick start

1. Copy this repository's CI files into your project (or use this repo as a template):

   ```
   .github/workflows/arm-mcp-ci.yml
   ci/
   .arm-mcp-ci.yaml.example
   ```

2. Optionally create `.arm-mcp-ci.yaml` from the example to customize languages and container images.

3. Open a pull request — the workflow runs automatically and posts a comment with migrate-ease findings and performance suggestions.

## Configuration

Create `.arm-mcp-ci.yaml` in the repository root:

```yaml
languages:
  - cpp
  - go

docker_images:
  - myorg/myapp:latest
```

Languages are auto-detected when omitted.

## Local testing

### Detect project metadata

```bash
pip install -r ci/requirements.txt
python ci/detect_project.py --json
```

### Run Arm MCP analysis (requires Docker)

```bash
docker pull armlimited/arm-mcp:latest
export LANGUAGES='["cpp"]'
export DOCKER_IMAGES='["debian:bookworm-slim"]'
python ci/run_analysis.py
cat ci-output/report.md
```

## Requirements

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
| PyYAML error in detect job | Ensure `pip install -r ci/requirements.txt` runs before `detect_project.py` |

## References

- [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server)
- [arm/mcp on GitHub](https://github.com/arm/mcp)
- [Automate x86 to Arm migration with GitHub Copilot](https://learn.arm.com/learning-paths/servers-and-cloud-computing/docker-mcp-toolkit/4-run-migration/)

## License

Apache-2.0 (same as Arm MCP Server)
