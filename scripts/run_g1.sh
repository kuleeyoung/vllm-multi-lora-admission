#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
work_dir=${LORA_WORK_DIR:-"$HOME/work/vllm-lora-admission"}
port=${LORA_PORT:-8018}
output=${1:?Provide a new output directory}
mkdir -p "$(dirname "$output")"
mkdir "$output"
output=$(realpath "$output")
overlay="$work_dir/b0-overlay"
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

cp configs/g1.json "$output/trajectory.json"
for limit in 2 4; do
  if curl -fsS --max-time 2 "$base_url/health" >/dev/null 2>&1; then
    echo "Port $port already serves vLLM" >&2
    exit 1
  fi
  events="$output/limit$limit-events.jsonl"
  PYTHONPATH="$overlay" LORA_TRACE_PATH="$events" LORA_MAX_LORAS="$limit" \
    bash scripts/serve_g0.sh > "$output/limit$limit-server.log" 2>&1 &
  server_pid=$!
  for attempt in {1..150}; do
    if curl -fsS --max-time 2 "$base_url/health" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
      tail -n 20 "$output/limit$limit-server.log" >&2
      exit 1
    fi
    sleep 1
  done
  curl -fsS --max-time 2 "$base_url/health"
  python3 -m bench.smoke --base-url "$base_url/v1" --base-model Qwen/Qwen3-0.6B \
    --max-tokens 24 --output "$output/limit$limit-warmup.jsonl"
  runs=(1)
  if [[ "$limit" == 2 ]]; then runs=(1 2 3); fi
  clients=()
  for run in "${runs[@]}"; do
    client="$output/l${limit}r${run}-client.jsonl"
    python3 -m bench.replay_g1 --run "l${limit}r${run}" --config "$output/trajectory.json" \
      --url "$base_url/v1/completions" --output "$client"
    clients+=("$client")
  done
  stop_server
  python3 -m bench.analyze_g1 --events "$events" --clients "${clients[@]}" --limit "$limit" \
    --output "$output/limit$limit-summary.json"
done
