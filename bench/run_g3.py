"""Run paired GPU experiments from one frozen configuration."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
import time
import urllib.request

from bench.smoke import request as warmup_request


def workload(config, scenario, seed):
    rng = random.Random(seed)
    prompts = ["Continue this sequence: 3, 6, 9,", "Complete the list: copper, silver, gold,",
               "Continue the alphabet: A, B, C, D,", "Write the next values: 2, 4, 8, 16,"]
    if "bursts" in scenario:
        spec = scenario["bursts"]
        planned = []
        for start in spec["starts_s"]:
            hot_tokens = rng.choice(spec["hot_output_options"])
            for pair in range(spec["hot_pairs"]):
                for adapter in "AB":
                    planned.append((start + pair * spec["hot_pair_interval_s"], adapter, hot_tokens))
            for adapter, offset in spec["cold_offsets_s"].items():
                planned.append((start + offset, adapter, spec["cold_output_tokens"]))
        scheduled = sorted((round(t + rng.uniform(0, spec["jitter_s"]), 6), adapter, tokens,
                            rng.choice(prompts)) for t, adapter, tokens in planned)
        return [{"index": i, "offset_s": offset, "model": model, "prompt": prompt, "max_tokens": tokens}
                for i, (offset, model, tokens, prompt) in enumerate(scheduled)]
    interval = 1 / scenario["rps"]
    pattern = scenario["adapters"]
    shift = rng.randrange(len(pattern))
    shift = scenario.get("adapter_phase", shift)
    if not isinstance(shift, int) or not 0 <= shift < len(pattern):
        raise ValueError("adapter_phase must be an index into the adapter pattern")
    records = []
    arrival_duration = scenario.get("arrival_duration_s", config["arrival_duration_s"])
    count = int(arrival_duration * scenario["rps"])
    prefix = scenario.get("adapter_prefix", [])
    if (not isinstance(prefix, list) or len(prefix) > count
            or any(adapter not in pattern for adapter in prefix)):
        raise ValueError("adapter_prefix must list adapters from the pattern within the arrival window")
    for index in range(count):
        adapter = prefix[index] if index < len(prefix) else pattern[(index + shift) % len(pattern)]
        records.append({"index": index, "offset_s": round(interval * (index + rng.uniform(0, 0.35)), 6),
                        "model": adapter, "prompt": rng.choice(prompts), "max_tokens": scenario["tokens"]})
    return records


def generate(base, run_id, row, start, ready, timeout, verify_response_identity=False):
    rid = f"g3-{run_id}-{row['index']:03d}"
    request = urllib.request.Request(base + "/v1/completions", headers={
        "Content-Type": "application/json", "X-Request-Id": rid}, data=json.dumps({
        "model": row["model"], "prompt": row["prompt"], "max_tokens": row["max_tokens"],
        "ignore_eos": True, "temperature": 0, "stream": True, "return_token_ids": True,
        "stream_options": {"include_usage": True}
    }).encode())
    ready.wait(timeout=10)
    planned = start[0] + row["offset_s"]
    time.sleep(max(0, planned - time.monotonic()))
    first = last = usage = server_id = response_model = None
    count = 0
    done = False
    sent = time.monotonic()
    result = {**row, "request_id": rid, "sent_s": sent, "lag_s": sent - planned}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in response:
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    done = True
                    break
                event = json.loads(payload)
                if "error" in event:
                    raise ValueError(str(event["error"]))
                server_id = event["id"]
                response_model = event.get("model")
                if verify_response_identity and (server_id != f"cmpl-{rid}" or response_model != row["model"]):
                    raise ValueError(f"Unexpected stream identity: {server_id}/{response_model}")
                for choice in event["choices"]:
                    tokens = choice.get("token_ids") or []
                    if tokens:
                        last = time.monotonic()
                        if first is None:
                            first = last
                        count += len(tokens)
                if event.get("usage"):
                    usage = event["usage"]["completion_tokens"]
                if time.monotonic() - sent > timeout:
                    raise TimeoutError("Request exceeded fixed timeout")
        if not done or not count or count != usage or count != row["max_tokens"]:
            raise ValueError(f"Invalid stream: done={done}, tokens={count}, usage={usage}")
        result.update(status="ok", ttft_s=first - sent,
                      tpot_s=(last - first) / (count - 1) if count > 1 else None)
    except (OSError, ValueError) as exc:
        result.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=str(exc))
    result.update(done_s=time.monotonic(), output_tokens=count, server_id=server_id,
                  response_model=response_model)
    return result


def gpu_samples(path, stop):
    with path.open("w", encoding="utf-8") as output:
        while not stop.is_set():
            probe = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4)
            if probe.returncode == 0:
                fields = probe.stdout.strip().split(",")
                try:
                    memory, util = map(int, fields)
                except ValueError:
                    pass
                else:
                    output.write(json.dumps({"time_s": time.monotonic(), "memory_mib": memory,
                                             "utilization_pct": util}) + "\n")
            stop.wait(0.75)


def replay(root, base, run_id, rows, config):
    root.mkdir()
    trajectory = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    (root / "trajectory.json").write_text(trajectory, encoding="utf-8")
    digest = hashlib.sha256(trajectory.encode()).hexdigest()
    index = []
    barrier = threading.Barrier(len(rows) + 1)
    stop = threading.Event()
    gpu = threading.Thread(target=gpu_samples, args=(root / "gpu.jsonl", stop))
    gpu.start()
    try:
        with (root / "client.jsonl").open("w", encoding="utf-8") as output, ThreadPoolExecutor(len(rows)) as pool:
            futures = [pool.submit(generate, base, run_id, row, index, barrier,
                                   config["request_timeout_s"], config.get("verify_response_identity", False))
                       for row in rows]
            index.append(time.monotonic() + 0.25)
            barrier.wait(timeout=10)
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                output.write(json.dumps(result) + "\n")
                output.flush()
    finally:
        stop.set()
        gpu.join()
    (root / "run.json").write_text(json.dumps({"run_id": run_id, "start_s": index[0],
        "end_s": max(row["done_s"] for row in results), "trajectory_sha256": digest}, indent=2))
    print(run_id, f"{sum(r['status'] == 'ok' for r in results)}/{len(rows)} successful", flush=True)


def wait_health(process, base):
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited with status {process.returncode}")
        try:
            with urllib.request.urlopen(base + "/health", timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError("vLLM startup timed out")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=Path("configs/g3.json"))
    p.add_argument("--seed", type=int, help="Replay one registered seed")
    p.add_argument("--scenario", help="Replay one registered scenario")
    args = p.parse_args()
    raw = args.config.read_bytes()
    config = json.loads(raw)
    registered_seeds = config["seeds"]
    if args.seed is not None:
        if args.seed not in registered_seeds:
            p.error("seed is not registered")
        config["seeds"] = [args.seed]
    if args.scenario is not None:
        if args.scenario not in config["scenarios"]:
            p.error("scenario is not registered")
        config["scenarios"] = {args.scenario: config["scenarios"][args.scenario]}
    root = args.output.resolve()
    root.mkdir(parents=True)
    (root / "config.json").write_bytes(raw if args.seed is None and args.scenario is None
                                      else (json.dumps(config, indent=2) + "\n").encode())
    overlay = root / "overlay"
    subprocess.run([sys.executable, "scripts/build_b0_overlay.py", "--output", str(overlay)], check=True)
    base = "http://127.0.0.1:" + os.environ.get("LORA_PORT", "8018")
    modes = config.get("modes", ["B0", "B1", "B2"])
    for seed in config["seeds"]:
        index = registered_seeds.index(seed) % len(modes)
        for mode in modes[index:] + modes[:index]:
            directory = root / str(seed) / mode
            directory.mkdir(parents=True)
            profile = config.get("mode_profiles", {}).get(mode, {})
            scheduler_mode = profile.get("scheduler_mode", mode)
            env = {**os.environ, "PYTHONPATH": str(overlay), "LORA_ADMISSION_MODE": scheduler_mode,
                   "LORA_TRACE_PATH": str(directory / "events.jsonl"),
                   "LORA_MAX_LORAS": str(profile.get("max_loras", 2)),
                   "LORA_TRACE_DETAIL": "summary", "LORA_TRACE_SAMPLE_EVERY": "32",
                   "LORA_WAIT_MS": str(config["admission"]["wait_ms"]),
                   "LORA_RESERVATION_TTL_MS": str(config["admission"]["ttl_ms"]),
                   "LORA_COOLDOWN_MS": str(config["admission"]["cooldown_ms"])}
            if scheduler_mode == "B3":
                rules = config["admission"]["followup"]
                env.update(LORA_COLD_ADAPTER_IDS=",".join(map(str, rules["cold_adapter_ids"])),
                           LORA_HOT_GUARD_MS=str(profile.get("hot_guard_ms", rules["hot_guard_ms"])),
                           LORA_FOLLOWUP_MS=str(rules["window_ms"]))
            with (directory / "server.log").open("w", encoding="utf-8") as log:
                server = subprocess.Popen(["bash", "scripts/serve_g0.sh"], env=env,
                                          stdout=log, stderr=subprocess.STDOUT)
                try:
                    wait_health(server, base)
                    warmup = [warmup_request(base + "/v1", name, "warmup", 120, 24) for name in "ABCD"]
                    if any(row["status"] != "ok" for row in warmup):
                        raise RuntimeError(f"Warmup failed: {warmup}")
                    (directory / "warmup.json").write_text(json.dumps(warmup, indent=2))
                    scenarios = list(config["scenarios"].items())
                    if config.get("alternate_scenario_order") and (index + modes.index(mode)) % 2:
                        scenarios.reverse()
                    for name, scenario in scenarios:
                        replay(directory / name, base, f"{seed}-{mode}-{name}",
                               workload(config, scenario, seed), config)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()


if __name__ == "__main__":
    main()
