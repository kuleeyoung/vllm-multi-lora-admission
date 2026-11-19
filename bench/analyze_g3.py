"""Analyze the fixed-window metrics and pair each scenario by seed."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median

from bench.analyze_g1 import read_jsonl


MODES = ("B0", "B1", "B2")


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def cohort(rows):
    values = [row["queue_ms"] for row in rows if row["queue_ms"] is not None]
    ok = [row for row in rows if row["status"] == "ok"]
    return {"requests": len(rows), "admitted": len(values), "failed": len(rows) - len(ok),
            "no_admit": len(rows) - len(values),
            "queue_p50_ms": percentile(values, 0.5), "queue_p95_ms": percentile(values, 0.95),
            "queue_p99_ms": percentile(values, 0.99),
            "over_500ms": sum(v >= 500 for v in values),
            "ttft_p95_s": percentile([row["ttft_s"] for row in ok], 0.95),
            "tpot_p95_s": percentile([row["tpot_s"] for row in ok if row["tpot_s"] is not None], 0.95)}


def measure(root, config, scenario, seed, mode, events):
    directory = root / str(seed) / mode / scenario
    manifest = json.loads((directory / "run.json").read_text())
    trajectory = (directory / "trajectory.json").read_bytes()
    if hashlib.sha256(trajectory).hexdigest() != manifest["trajectory_sha256"]:
        raise ValueError(f"Trajectory hash mismatch in {directory}")
    start = manifest["start_s"]
    cutoff = start + config["measurement_duration_s"]
    requests = read_jsonl(directory / "client.jsonl")
    planned = json.loads(trajectory)
    if len(requests) != len(planned) or sorted(r["index"] for r in requests) != list(range(len(planned))):
        raise ValueError(f"Incomplete client log in {directory}")
    profile = config.get("mode_profiles", {}).get(mode, {})
    scheduler_mode = profile.get("scheduler_mode", mode)
    max_loras = profile.get("max_loras", 2)
    loaded = {e["pid"] for e in events if e["event"] == "scheduler_loaded"
              and e["mode"] == scheduler_mode
              and ("hot_guard_ms" not in profile or e.get("hot_guard_ms") == profile["hot_guard_ms"])}
    if "max_loras" in profile:
        loaded &= {e["pid"] for e in events if e["event"] == "scheduler_capacity"
                   and e["mode"] == scheduler_mode and e["max_loras"] == max_loras}
    prefix = f"cmpl-g3-{manifest['run_id']}-"
    queue_events = {}
    for event in events:
        rid = event.get("request_id", "")
        if rid.startswith(prefix) and event["event"] in {"queued", "admit", "finished", "preempted"}:
            queue_events.setdefault(rid, []).append(event)
    by_public_id = {}
    for rid, chain in queue_events.items():
        public_id = re.sub(r"-0-[0-9a-f]+$", "", rid)
        if public_id in by_public_id:
            raise ValueError(f"Duplicate server request {public_id}")
        by_public_id[public_id] = chain
    preemptions = 0
    active_bound = 0
    for row in requests:
        expected = planned[row["index"]]
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError(f"Client/trajectory mismatch for {row['request_id']}")
        public_id = "cmpl-" + row["request_id"]
        chain = by_public_id.get(public_id, [])
        if row["server_id"] not in (None, public_id) or any(
            e["pid"] not in loaded or e["adapter"] != row["model"] for e in chain
        ):
            raise ValueError(f"Request identity mismatch for {row['request_id']}")
        counts = Counter(e["event"] for e in chain)
        preemptions += counts["preempted"]
        if row["status"] == "ok" and any(counts[key] != 1 for key in ("queued", "finished")):
            raise ValueError(f"Missing request lifecycle for {row['request_id']}")
        queued = next((e for e in chain if e["event"] == "queued"), None)
        admit = next((e for e in chain if e["event"] == "admit"), None)
        if row["status"] == "ok" and not admit:
            raise ValueError(f"No admission for {row['request_id']}")
        row["queue_ms"] = (admit["time_ns"] - queued["time_ns"]) / 1e6 if admit and queued else None
        if admit:
            active_bound = max(active_bound, len(set(admit["active_before"]) | {"ABCD".index(row["model"]) + 1}))
    if active_bound > max_loras:
        raise ValueError("Configured LoRA capacity was exceeded")
    policy = Counter(e["event"] for e in events if e.get("target_id", "").startswith(prefix))
    if scheduler_mode == "B0" and policy:
        raise ValueError("B0 emitted policy actions")
    done = [r for r in requests if r["status"] == "ok" and r["done_s"] <= cutoff]
    good = [r for r in done if r["ttft_s"] <= config["slo"]["ttft_s"] and
            (r["tpot_s"] is None or r["tpot_s"] <= config["slo"]["tpot_s"])]
    window = config["measurement_duration_s"]
    active_end = min(manifest["end_s"], cutoff)
    samples = [e for e in events if e["event"] == "schedule_sample"
               and start <= e["time_ns"] / 1e9 <= active_end]
    gpu = [g for g in read_jsonl(directory / "gpu.jsonl")
           if start <= g["time_s"] <= active_end]
    cold = config["scenarios"][scenario]["cold"]
    groups = {model: cohort([r for r in requests if r["model"] == model]) for model in "ABCD"}
    groups["cold"] = cohort([r for r in requests if r["model"] in cold])
    groups["hot"] = cohort([r for r in requests if r["model"] not in cold])
    groups["all"] = cohort(requests)
    span = manifest["end_s"] - start
    all_completed_tokens = sum(r["output_tokens"] for r in requests if r["status"] == "ok")
    return {"scenario": scenario, "seed": seed, "mode": mode, "sha256": manifest["trajectory_sha256"],
            "max_loras": max_loras, "peak_active_loras_observed": active_bound,
            "groups": groups, "fixed_window_s": window, "client_span_s": span,
            "completed_in_window": len(done), "good_in_window": len(good), "goodput_rps": len(good) / window,
            "throughput_rps": len(done) / window, "output_tokens_per_s": sum(r["output_tokens"] for r in done) / window,
            "burst_output_tokens_per_s": all_completed_tokens / span,
            "timeouts": sum(r["status"] == "timeout" for r in requests), "preemptions": preemptions,
            "lag_max_ms": max(r["lag_s"] for r in requests) * 1000,
            "batch_fill_mean": (sum(e["batch_requests"] / e["max_active_requests"] for e in samples) / len(samples)
                                if samples else None),
            "batch_requests_mean": (sum(e["batch_requests"] for e in samples) / len(samples) if samples else None),
            "scheduler_sample_count": len(samples),
            "scheduler_p95_us": percentile([e["cpu_ns"] / 1000 for e in samples], 0.95),
            "peak_gpu_mib_sampled": max((g["memory_mib"] for g in gpu), default=None),
            "gpu_util_mean_sampled": (sum(g["utilization_pct"] for g in gpu) / len(gpu) if gpu else None),
            "policy_counts": dict(policy)}


def compare(rows, config):
    index = {(r["scenario"], r["seed"], r["mode"]): r for r in rows}
    pairs = []
    modes = config.get("modes", MODES)
    comparisons = config.get("comparisons", list(zip(modes, modes[1:])))
    for scenario in config["scenarios"]:
        for seed in config["seeds"]:
            group = [index[scenario, seed, mode] for mode in modes]
            if len({r["sha256"] for r in group}) != 1:
                raise ValueError(f"Unpaired trajectories for {scenario}/{seed}")
            for base_mode, candidate_mode in comparisons:
                base = index[scenario, seed, base_mode]
                candidate = index[scenario, seed, candidate_mode]
                queues = [r["groups"]["cold"]["queue_p95_ms"] for r in (base, candidate)]
                reduction = ((1 - queues[1] / queues[0]) * 100
                             if None not in queues and queues[0] > 0 else None)
                loss = ((1 - candidate["goodput_rps"] / base["goodput_rps"]) * 100
                        if base["goodput_rps"] > 0 else None)
                competing = base["mode"] == "B1" and base["policy_counts"].get("slot_taken", 0) > 0
                extra = {}
                eligible = competing
                hot_ok = True
                profiles = config.get("mode_profiles", {})
                capacity_pair = base["max_loras"] != candidate["max_loras"]
                if capacity_pair or profiles.get(candidate["mode"], {}).get("scheduler_mode", candidate["mode"]) == "B3":
                    hot = [r["groups"]["hot"]["queue_p95_ms"] for r in (base, candidate)]
                    hot_delta = hot[1] - hot[0] if None not in hot else None
                    hot_ok = hot_delta is not None and hot_delta <= config["targets"]["max_hot_p95_increase_ms"]
                    extra = {"hot_p95_delta_ms": hot_delta}
                    if capacity_pair:
                        eligible = candidate["peak_active_loras_observed"] > base["max_loras"]
                        extra.update(capacity_exercised=eligible)
                    else:
                        followups = candidate["policy_counts"].get("cold_followup_selected", 0)
                        eligible = followups > 0
                        extra.update(b3_followups=followups,
                                     b3_hot_guard=candidate["policy_counts"].get("hot_guard_kept_order", 0))
                pairs.append({"scenario": scenario, "seed": seed, "comparison": f"{candidate['mode']}/{base['mode']}",
                              "cold_p95_delta_ms": queues[1] - queues[0] if None not in queues else None,
                              "cold_p95_reduction_pct": reduction, "goodput_loss_pct": loss,
                              "goodput_delta_rps": candidate["goodput_rps"] - base["goodput_rps"],
                              "b1_competing": competing,
                              "meets_targets": (eligible and hot_ok and reduction is not None and loss is not None
                                  and reduction >= config["targets"]["cold_p95_reduction_pct"]
                                  and loss <= config["targets"]["max_goodput_loss_pct"]), **extra})
    return pairs


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    root = args.directory
    config = json.loads((root / "config.json").read_text())
    rows = []
    for seed in config["seeds"]:
        for mode in config.get("modes", MODES):
            events = read_jsonl(root / str(seed) / mode / "events.jsonl")
            for scenario in config["scenarios"]:
                rows.append(measure(root, config, scenario, seed, mode, events))
    pairs = compare(rows, config)
    (root / "summary.json").write_text(json.dumps({"runs": rows, "pairs": pairs}, indent=2) + "\n")
    write_csv(root / "pairs.csv", pairs)
    write_csv(root / "runs.csv", [
        {key: value for key, value in row.items() if key not in {"groups", "policy_counts"}}
        for row in rows
    ])
    write_csv(root / "cohorts.csv", [
        {"scenario": row["scenario"], "seed": row["seed"], "mode": row["mode"], "cohort": name, **stats}
        for row in rows for name, stats in row["groups"].items()
    ])
    for scenario in config["scenarios"]:
        modes = config.get("modes", MODES)
        comparisons = config.get("comparisons", [(modes[-2], modes[-1])])
        for base, candidate in comparisons:
            label = f"{candidate}/{base}"
            matched = [r for r in pairs if r["scenario"] == scenario and r["comparison"] == label]
            deltas = [r["cold_p95_delta_ms"] for r in matched if r["cold_p95_delta_ms"] is not None]
            print(scenario, label, "cold delta ms median", round(median(deltas), 2) if deltas else None,
                  "eligible", sum(bool(r.get("capacity_exercised", r.get("b3_followups", r["b1_competing"])))
                                  for r in matched),
                  "target met", sum(r["meets_targets"] for r in matched))


if __name__ == "__main__":
    main()
