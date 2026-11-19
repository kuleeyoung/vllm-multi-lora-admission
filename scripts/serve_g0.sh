#!/usr/bin/env bash
set -euo pipefail

work_dir=${LORA_WORK_DIR:-"$HOME/work/vllm-lora-admission"}
exec "$work_dir/.venv/bin/vllm" serve "$work_dir/models/Qwen3-0.6B" \
  --served-model-name Qwen/Qwen3-0.6B --host 127.0.0.1 --port "${LORA_PORT:-8018}" \
  --dtype bfloat16 --max-model-len 512 --max-num-seqs 8 \
  --gpu-memory-utilization 0.5 --enforce-eager --no-enable-prefix-caching \
  --enable-lora --max-lora-rank 8 --max-loras "${LORA_MAX_LORAS:-2}" --max-cpu-loras 4 \
  --enable-request-id-headers \
  --lora-modules "A=$work_dir/adapters/A" "B=$work_dir/adapters/B" \
                 "C=$work_dir/adapters/C" "D=$work_dir/adapters/D"
