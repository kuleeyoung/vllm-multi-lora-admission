#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
workspace=${LORA_WORK_DIR:-"$HOME/work/vllm-lora-admission"}
clean_workspace=${1:?Provide a new WSL workspace directory}
output=${2:?Provide a new result directory}
mkdir "$clean_workspace"
clean_workspace=$(realpath "$clean_workspace")
mkdir -p "$(dirname "$output")"
output=$(realpath -m "$output")
if [[ -e "$output" ]]; then
  echo "Output directory already exists: $output" >&2
  exit 1
fi
python3 -m venv "$clean_workspace/.venv"
python="$clean_workspace/.venv/bin/python"
"$python" -m pip install --only-binary=:all: --disable-pip-version-check \
  -r env/requirements-wsl.txt > "$clean_workspace/install.log" 2>&1
"$python" -m pip check
"$python" -m pip freeze > "$clean_workspace/freeze.txt"
diff -u env/requirements-wsl.txt "$clean_workspace/freeze.txt"
ln -s "$workspace/models" "$clean_workspace/models"
ln -s "$workspace/adapters" "$clean_workspace/adapters"
LORA_WORK_DIR="$clean_workspace" "$python" -m bench.run_g3 "$output" \
  --seed 713 --scenario hot-overload-long
cp "$clean_workspace/install.log" "$clean_workspace/freeze.txt" "$output/"
python3 -m bench.analyze_g3 "$output"
