#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
output=${1:?Provide a new output directory}
mkdir -p "$(dirname "$output")"
mkdir "$output"
port=${LORA_PORT:-8018}
url="http://127.0.0.1:$port"
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

for profile in recommended rollback; do
  if curl -fsS --max-time 2 "$url/health" >/dev/null 2>&1; then
    echo "Port $port already serves vLLM" >&2
    exit 1
  fi
  args=()
  expected=3
  if [[ "$profile" == rollback ]]; then
    args=(--rollback)
    expected=2
  fi
  log="$output/$profile-server.log"
  LORA_MAX_LORAS=4 bash scripts/serve.sh "${args[@]}" > "$log" 2>&1 &
  server_pid=$!
  for attempt in {1..150}; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
      tail -n 20 "$log" >&2
      exit 1
    fi
    if curl -fsS --max-time 2 "$url/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  curl -fsS --max-time 2 "$url/health"
  grep -F "'max_loras': $expected" "$log" > "$output/$profile-capacity.txt"
  python3 -m bench.smoke --base-url "$url/v1" --base-model Qwen/Qwen3-0.6B \
    --max-tokens 24 --output "$output/$profile-streams.jsonl"
  python3 -m bench.check_binding --streams "$output/$profile-streams.jsonl" \
    --output "$output/$profile-binding.json"
  stop_server
done
