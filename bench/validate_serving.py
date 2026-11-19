"""Exercise the actual release launcher across repeated traffic and rollback."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

from bench.analyze_g1 import read_jsonl
from bench.analyze_g3 import percentile, write_csv
from bench.run_g3 import replay, wait_health, workload


EXPECTED_MODELS = {"Qwen/Qwen3-0.6B", *"ABCD"}


def verify_models(base):
    with urllib.request.urlopen(base + "/v1/models", timeout=5) as response:
        models = json.load(response)
    ids = {row["id"] for row in models["data"]}
    if ids != EXPECTED_MODELS:
        raise ValueError(f"Unexpected served model IDs: {sorted(ids)}")
    return models


def rss_kib(pid):
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return None
    rss = re.search(r"^VmRSS:\s+(\d+)", status, re.MULTILINE)
    return int(rss[1]) if rss else None


def fd_count(pid):
    return sum(1 for _ in Path(f"/proc/{pid}/fd").iterdir())


def shm_entries():
    return sorted(path.name for path in Path("/dev/shm").iterdir())


def idle_sample(profile, moment, pid, engine_pid):
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         check=True, capture_output=True, text=True, timeout=5)
    return {"profile": profile, "moment": moment, "after_monotonic_s": time.monotonic(),
            "gpu_used_mib": int(gpu.stdout.strip()), "server_rss_kib": rss_kib(pid),
            "engine_rss_kib": rss_kib(engine_pid),
            "server_fd_count": fd_count(pid), "engine_fd_count": fd_count(engine_pid)}


def summarize(directory, profile, cycle, scenario, config):
    run = json.loads((directory / "run.json").read_text())
    rows = read_jsonl(directory / "client.jsonl")
    if len({row["request_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate request ID in one serving window")
    cutoff = run["start_s"] + config["measurement_duration_s"]
    complete = [r for r in rows if r["status"] == "ok" and r["done_s"] <= cutoff]
    good = [r for r in complete if r["ttft_s"] <= config["slo"]["ttft_s"] and
            (r["tpot_s"] is None or r["tpot_s"] <= config["slo"]["tpot_s"])]
    if len(complete) != len(rows):
        raise ValueError(f"Incomplete serving window: {directory}")
    return {"profile": profile, "cycle": cycle, "scenario": scenario,
            "requests": len(rows), "good": len(good),
            "goodput_rps": len(good) / config["measurement_duration_s"],
            "ttft_p95_s": percentile([r["ttft_s"] for r in rows], 0.95),
            "tpot_p95_s": percentile([r["tpot_s"] for r in rows if r["tpot_s"] is not None], 0.95),
            "span_s": run["end_s"] - run["start_s"], "trajectory_sha256": run["trajectory_sha256"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--config", type=Path, default=Path("configs/serving-acceptance.json"))
    p.add_argument("--startup-only", action="store_true", help="Check startup and shutdown without inference")
    args = p.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    root = args.directory.resolve()
    root.mkdir(parents=True)
    (root / "config.json").write_bytes(args.config.read_bytes())
    base = "http://127.0.0.1:" + os.environ.get("LORA_PORT", "8018")
    rows, idle, starts, shutdowns = [], [], [], []
    track_shutdown = config.get("track_shutdown_resources", False)
    for name, slots, cycles, flags in (
        ("recommended", 3, config["recommended_cycles"], []),
        ("rollback", 2, 1, ["--rollback"]),
    ):
        try:
            with urllib.request.urlopen(base + "/health", timeout=1):
                raise RuntimeError(f"The serving port is already in use: {base}")
        except OSError:
            pass
        directory = root / name
        directory.mkdir()
        log_path = directory / "server.log"
        shared = {"before_start": shm_entries()} if track_shutdown else None
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(["bash", "scripts/serve.sh", *flags], stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_health(process, base)
                models = verify_models(base)
                (directory / "models.json").write_text(json.dumps(models, indent=2))
                startup = log_path.read_text(encoding="utf-8")
                engines = set(re.findall(r"EngineCore pid=(\d+)", startup))
                if len(engines) != 1 or f"'max_loras': {slots}" not in startup or "'max_num_seqs': 8" not in startup:
                    raise ValueError(f"Unexpected startup configuration in {log_path}")
                engine = int(engines.pop())
                starts.append({"profile": name, "max_loras": slots, "server_pid": process.pid,
                               "engine_pid": engine})
                idle.append(idle_sample(name, "startup", process.pid, engine))
                if shared is not None:
                    shared["startup"] = shm_entries()
                for cycle in range(1, (0 if args.startup_only else cycles) + 1):
                    for scenario, spec in config["scenarios"].items():
                        run = directory / f"{cycle}-{scenario}"
                        planned = workload(config, spec, config["seed"])
                        replay(run, base, f"serving-{name}-{cycle}-{scenario}", planned, config)
                        stats = summarize(run, name, cycle, scenario, config)
                        if stats["requests"] != len(planned):
                            raise ValueError(f"Missing records in {run}")
                        rows.append(stats)
                    time.sleep(1)
                    wait_health(process, base)
                    verify_models(base)
                    idle.append(idle_sample(name, f"cycle-{cycle}", process.pid, engine))
                    if shared is not None:
                        shared[f"cycle-{cycle}"] = shm_entries()
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if Path(f"/proc/{engine}").exists():
            raise RuntimeError(f"Engine {engine} survived profile shutdown")
        if shared is not None:
            before = set(shared["before_start"])
            shared["after_exit"] = shm_entries()
            deadline = time.monotonic() + 5
            settled = shared["after_exit"]
            while set(settled) - before and time.monotonic() < deadline:
                time.sleep(0.25)
                settled = shm_entries()
            shared["after_settle"] = settled
            warnings = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines()
                        if re.search(r"resource_tracker: There appear to be \d+ leaked semaphore", line)]
            (directory / "shm-snapshots.json").write_text(json.dumps(shared, indent=2) + "\n")
            shutdowns.append({"profile": name, "resource_tracker_warnings": warnings,
                              "new_entries_after_exit": sorted(set(shared["after_exit"]) - before),
                              "new_entries_after_settle": sorted(set(settled) - before)})
    if not args.startup_only:
        for scenario in config["scenarios"]:
            if len({row["trajectory_sha256"] for row in rows if row["scenario"] == scenario}) != 1:
                raise ValueError(f"Trajectory changed across serving windows: {scenario}")
        write_csv(root / "windows.csv", rows)
    write_csv(root / "idle-samples.csv", idle)
    (root / "summary.json").write_text(json.dumps({"passed": True, "profiles": starts, "windows": rows,
        "requests": sum(row["requests"] for row in rows), "startup_only": args.startup_only,
        "shutdown_resources": shutdowns}, indent=2) + "\n")


if __name__ == "__main__":
    main()
