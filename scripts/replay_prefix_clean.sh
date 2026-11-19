#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
workspace=$(realpath -m "${1:?Provide a new Linux workspace directory}")
output=$(realpath -m "${2:?Provide a new result directory}")
if [[ -e "$workspace" || -e "$output" ]]; then
  echo "Workspace and result directory must both be new." >&2
  exit 1
fi
mkdir -p "$(dirname "$workspace")"
mkdir "$workspace"

python3.12 -m venv "$workspace/.venv"
python="$workspace/.venv/bin/python"
echo "Installing locked wheels"
"$python" -m pip install --only-binary=:all: --disable-pip-version-check \
  -r env/requirements-wsl.txt > "$workspace/install.log" 2>&1
"$python" -m pip check
"$python" -m pip freeze > "$workspace/freeze.txt"
diff -u env/requirements-wsl.txt "$workspace/freeze.txt"

echo "Preparing pinned model and generating four adapters"
model="$workspace/models/Qwen3-0.6B"
"$python" scripts/download_model.py --output "$model"
"$python" scripts/make_adapters.py --model "$model" --output "$workspace/adapters"

echo "Replaying the two prefixes at both capacities"
LORA_WORK_DIR="$workspace" "$python" -m bench.run_g3 "$output" \
  --config configs/g3-prefix-order.json --seed 26813
cp "$model/download-manifest.json" "$workspace/freeze.txt" "$output/"
"$python" -m bench.analyze_g3 "$output"
"$python" -m bench.analyze_capacity "$output"
"$python" -m bench.analyze_capacity_boundary "$output"
"$python" -m bench.analyze_arrival_order "$output"
