#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' 'Usage: bash scripts/serve.sh [--rollback]' \
    'Default: B0, max_loras=3. Rollback: B0, max_loras=2.'
}

case "$#:${1:-}" in
  0:) max_loras=3 ;;
  1:--rollback) max_loras=2 ;;
  1:--help | 1:-h) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# The serving entry uses upstream B0 from the isolated environment.
exec env -u PYTHONPATH -u LORA_TRACE_PATH -u LORA_ADMISSION_MODE \
  LORA_MAX_LORAS="$max_loras" bash "$script_dir/serve_g0.sh"
