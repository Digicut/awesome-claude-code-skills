#!/usr/bin/env bash
set -euo pipefail
setup_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for dependency in python3 git; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "Eksik araç: $dependency. Önce WSL/Ubuntu ortamında bu aracı kur." >&2
    exit 1
  fi
done
python3 "$setup_dir/scripts/skills.py" install "$@"
