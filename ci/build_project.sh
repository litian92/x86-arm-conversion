#!/usr/bin/env bash
# Build the repository on the current runner architecture.
set -euo pipefail

ARCH="${1:-$(uname -m)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() {
  echo "[build][${ARCH}] $*"
}

run_cmd() {
  log "Running: $*"
  eval "$@"
}

load_config_command() {
  local key="$1"
  python3 - <<'PY' "$key"
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

key = sys.argv[1]
root = Path(".")
config = {}
for name in (".arm-mcp-ci.yaml", ".arm-mcp-ci.yml"):
    path = root / name
    if path.exists() and yaml is not None:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        break

build = config.get("build", {}) if isinstance(config, dict) else {}
value = build.get(key) or build.get("default") or build.get("command")
print(value or "")
PY
}

if configured="$(load_config_command "$ARCH")" && [[ -n "$configured" ]]; then
  run_cmd "$configured"
  exit 0
fi

if [[ -f Makefile ]] && grep -qE '^[a-zA-Z0-9_.-]+:' Makefile; then
  run_cmd "make -j$(nproc)"
  exit 0
fi

if [[ -f CMakeLists.txt ]]; then
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build -j"$(nproc)"
  exit 0
fi

if [[ -f go.mod ]]; then
  run_cmd "go build ./..."
  exit 0
fi

if [[ -f Cargo.toml ]]; then
  run_cmd "cargo build --release"
  exit 0
fi

if [[ -f package.json ]]; then
  if command -v npm >/dev/null 2>&1; then
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
    if jq -e '.scripts.build' package.json >/dev/null 2>&1; then
      run_cmd "npm run build"
      exit 0
    fi
  fi
fi

if [[ -f pyproject.toml || -f setup.py ]]; then
  python3 -m pip install --upgrade pip
  if [[ -f pyproject.toml ]]; then
    python3 -m pip install .
  else
    python3 -m pip install -e .
  fi
  exit 0
fi

if [[ -f Dockerfile ]]; then
  log "No native build system detected; validating Dockerfile syntax"
  docker build -f Dockerfile .
  exit 0
fi

log "No supported build system found. Add commands under build: in .arm-mcp-ci.yaml"
exit 1
