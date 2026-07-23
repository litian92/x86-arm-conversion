# ARM MCP Analysis CI

GitHub Actions workflow that runs [Arm MCP Server](https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server) analysis inside a container and posts actionable feedback on pull requests.

## What it does

| Job | Purpose |
| --- | --- |
| **Detect project** | Finds languages, Dockerfiles, and container base images |
| **ARM MCP analysis** | Runs Arm MCP tools via `armlimited/arm-mcp` Docker image |
| **Post PR feedback** | Updates a single PR comment with migration and optimization guidance |
| **ARM MCP AI analysis** _(optional)_ | LLM-driven tool orchestration when PR has the `arm-mcp-ai` label |
| **Post AI feedback** _(optional)_ | Posts a separate AI analysis comment on the PR |

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

**Scripted mode** (deterministic, no API key):

```bash
docker pull armlimited/arm-mcp:latest
export LANGUAGES='["cpp"]'
export DOCKER_IMAGES='["debian:bookworm-slim"]'
python ci/run_analysis.py
cat ci-output/report.md
```

**AI mode** (LLM selects and chains MCP tools dynamically):

```bash
cp .arm-mcp-ai.yaml.example .arm-mcp-ai.yaml
# Edit provider, model, and api_key_env

export OPENAI_API_KEY=sk-...
export LANGUAGES='["cpp"]'
export DOCKER_IMAGES='["debian:bookworm-slim"]'
python ci/ai_analysis.py
cat ci-output/report.md
```

AI mode works with any OpenAI-compatible API (OpenAI, Azure, Ollama, custom endpoints) or Anthropic Claude. Configure via `.arm-mcp-ai.yaml` or environment variables:

| Variable | Purpose |
| --- | --- |
| `ARM_MCP_AI_PROVIDER` | `openai`, `openai_compat`, `ollama`, `custom`, `anthropic`, `claude` |
| `ARM_MCP_AI_MODEL` | Model name (e.g. `gpt-4o`, `claude-sonnet-4-20250514`) |
| `ARM_MCP_AI_BASE_URL` | Override API base URL for custom/OpenAI-compatible endpoints |
| `ARM_MCP_AI_API_KEY_ENV` | Env var name holding the API key (default: provider-specific) |
| `ARM_MCP_AI_MAX_ITERATIONS` | Max tool-use loop iterations (default: 20) |

As Arm MCP adds new tools, AI mode discovers them automatically via `list_tools` — no script changes required.

### AI mode in GitHub Actions (label-triggered)

The workflow runs scripted analysis on every PR. **AI analysis is optional** — add the `arm-mcp-ai` label to a pull request to enable it.

1. Add a repository secret: `OPENAI_API_KEY`, `ARM_MCP_AI_API_KEY`, or `ANTHROPIC_API_KEY`
2. (Optional) Set repository variables `ARM_MCP_AI_PROVIDER` and `ARM_MCP_AI_MODEL` to override defaults (`openai` / `gpt-4o`)
3. (Optional) Commit `.arm-mcp-ai.yaml` for provider-specific settings (custom base URL, task prompt, etc.)
4. Add the **`arm-mcp-ai`** label to the PR

The workflow posts two separate PR comments: the standard scripted report and an **Arm MCP AI Analysis Report**. Re-running happens on new commits (`synchronize`) while the label remains, or when the label is first added (`labeled`).

## Requirements

- **Docker** on the analysis job runner (provided on `ubuntu-latest` GitHub-hosted runners)
- **`armlimited/arm-mcp`** image pulled at runtime (no API keys required for scripted mode)
- **LLM API key** required only for AI mode (`ci/ai_analysis.py`)

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
