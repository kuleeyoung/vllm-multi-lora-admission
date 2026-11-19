#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
work_dir=${LORA_WORK_DIR:-"$HOME/work/vllm-lora-admission"}
port=${LORA_PORT:-8018}
output=${1:?Provide a new output directory}
config=${2:-configs/g2.json}
mkdir -p "$(dirname "$output")"
mkdir "$output"
output=$(realpath "$output")
overlay="$output/overlay"
"$work_dir/.venv/bin/python" scripts/build_b0_overlay.py --output "$overlay"
base_url="http://127.0.0.1:$port"
server_pid=
stop_server() {
  if [[ -n "$server_pid" ]]; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" || true
    server_pid=
  fi
}
trap stop_server EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cp "$config" "$output/trajectory.json"
for mode in B0 B1 B2; do
  if curl -fsS --max-time 2 "$base_url/health" >/dev/null 2>&1; then
    echo "Port $port already serves vLLM" >&2
    exit 1
  fi
  PYTHONPATH="$overlay" LORA_TRACE_PATH="$output/$mode-events.jsonl" \
    LORA_ADMISSION_MODE="$mode" LORA_MAX_LORAS=2 LORA_WAIT_MS=500 \
    LORA_RESERVATION_TTL_MS=10000 LORA_COOLDOWN_MS=1000 \
    bash scripts/serve_g0.sh > "$output/$mode-server.log" 2>&1 &
  server_pid=$!
  for attempt in {1..150}; do
    if curl -fsS --max-time 2 "$base_url/health" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
      tail -n 20 "$output/$mode-server.log" >&2
      exit 1
    fi
    sleep 1
  done
  curl -fsS --max-time 2 "$base_url/health"
  python3 -m bench.smoke --base-url "$base_url/v1" --base-model Qwen/Qwen3-0.6B \
    --max-tokens 24 --output "$output/$mode-smoke.jsonl"
  python3 -m bench.check_binding --streams "$output/$mode-smoke.jsonl" \
    --output "$output/$mode-binding.json"
  python3 -m bench.replay_g1 --run "$mode" --config "$output/trajectory.json" \
    --url "$base_url/v1/completions" --output "$output/$mode-client.jsonl"
  stop_server
done
python3 -m bench.analyze_g2 "$output"
