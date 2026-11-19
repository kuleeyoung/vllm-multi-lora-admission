"""Compare two adapter orders at fixed capacity using trace evidence."""

import argparse
from collections import Counter
import json
from pathlib import Path

from bench.analyze_competition import load, queue_ms
from bench.analyze_g1 import read_jsonl
from bench.analyze_g3 import percentile, write_csv


ORDERS = ("hot-first", "cold-first")
ADAPTERS = "ABCD"


def verify_order_pair(hot, cold, shared_suffix_from_index=None):
    def without_adapters(rows):
        return [{key: value for key, value in row.items() if key != "model"} for row in rows]

    if without_adapters(hot) != without_adapters(cold):
        raise ValueError("Order pair differs in non-adapter request fields")
    if Counter(row["model"] for row in hot) != Counter(row["model"] for row in cold):
        raise ValueError("Order pair differs in adapter request counts")
    if [row["model"] for row in hot[:2]] != ["A", "B"] or [row["model"] for row in cold[:2]] != ["C", "D"]:
        raise ValueError("Unexpected opening adapter order")
    if shared_suffix_from_index is not None:
        if not 0 < shared_suffix_from_index < len(hot):
            raise ValueError("Shared suffix must follow a nonempty prefix")
        if hot[shared_suffix_from_index:] != cold[shared_suffix_from_index:]:
            raise ValueError("Order pair differs after the experimental prefix")


def suffix_metrics(directory, scenario, start, cold):
    clients, events, _ = load(directory, scenario)
    queues = {adapter: [] for adapter in ADAPTERS}
    for index, row in clients.items():
        if index >= start:
            queues[row["model"]].append(queue_ms(events[index]))
    tail = {adapter: percentile(values, 0.95) for adapter, values in queues.items() if values}
    cohorts = {
        "hot": [value for adapter in ADAPTERS if adapter not in cold for value in queues[adapter]],
        "cold": [value for adapter in ADAPTERS if adapter in cold for value in queues[adapter]],
    }
    return {"suffix_requests": sum(map(len, queues.values())),
            "suffix_slowest_adapter": max(tail, key=tail.__getitem__),
            **{f"suffix_{adapter}_p95_ms": value for adapter, value in tail.items()},
            **{f"suffix_{label}_p95_ms": percentile(values, 0.95) for label, values in cohorts.items()}}


def full_capacity(events, manifest, limit):
    prefix = f"cmpl-g3-{manifest['run_id']}-"
    admissions = (event for event in events if event["event"] == "admit"
                  and event["request_id"].startswith(prefix))
    start = manifest["start_s"]
    for event in admissions:
        before = set(event["active_before"])
        admitted = ADAPTERS.index(event["adapter"]) + 1
        if len(before) == limit - 1 and admitted not in before:
            full = "".join(ADAPTERS[index - 1] for index in sorted(before | {admitted}))
            offset = event["time_ns"] / 1e9 - start
            outsider = next((row for row in admissions if row["adapter"] not in full), None)
            outside_offset = outsider["time_ns"] / 1e9 - start if outsider else None
            return full, offset, outsider["adapter"] if outsider else "", outside_offset
    return "", None, "", None


def run_row(root, run, events):
    scenario, seed, mode = run["scenario"], run["seed"], run["mode"]
    directory = root / str(seed) / mode / scenario
    manifest = json.loads((directory / "run.json").read_bytes())
    groups = run["groups"]
    if (groups["all"]["requests"] != run["completed_in_window"]
            or groups["all"]["no_admit"] or run["preemptions"]):
        raise ValueError(f"Incomplete or preempted run: {directory}")
    full, offset, outsider, outside_offset = full_capacity(events, manifest, run["max_loras"])
    tail = {adapter: groups[adapter]["queue_p95_ms"] for adapter in ADAPTERS}
    slowest = max(tail, key=tail.__getitem__)
    return {"seed": seed, "mode": mode, "scenario": scenario,
            "first_full_set": full, "first_full_offset_s": offset,
            "first_outside_adapter": outsider, "first_outside_offset_s": outside_offset,
            "slowest_adapter": slowest, "slowest_in_first_full_set": slowest in full,
            **{f"{adapter}_p95_ms": value for adapter, value in tail.items()},
            "hot_p95_ms": groups["hot"]["queue_p95_ms"],
            "cold_p95_ms": groups["cold"]["queue_p95_ms"],
            "goodput_rps": run["goodput_rps"]}


def compare_orders(root):
    config = json.loads((root / "config.json").read_bytes())
    suffix = config.get("shared_suffix_from_index")
    summary = json.loads((root / "summary.json").read_bytes())
    index = {(row["seed"], row["mode"], row["scenario"]): row for row in summary["runs"]}
    results, pairs = [], []
    for seed, mode in dict.fromkeys((seed, mode) for seed, mode, _ in index):
        directory = root / str(seed) / mode
        trajectories = [json.loads((directory / order / "trajectory.json").read_bytes())
                        for order in ORDERS]
        verify_order_pair(*trajectories, shared_suffix_from_index=suffix)
        events = read_jsonl(directory / "events.jsonl")
        hot, cold = [run_row(root, index[seed, mode, order], events) for order in ORDERS]
        results.extend((hot, cold))
        pair = {"seed": seed, "mode": mode,
                "hot_first_slowest": hot["slowest_adapter"],
                "cold_first_slowest": cold["slowest_adapter"]}
        for key in ("hot_p95_ms", "cold_p95_ms", "goodput_rps"):
            pair[f"{key}_delta"] = cold[key] - hot[key]
        if suffix is not None:
            for order, row in zip(ORDERS, (hot, cold)):
                row.update(suffix_metrics(directory, order, suffix, config["scenarios"][order]["cold"]))
            pair.update(hot_first_suffix_slowest=hot["suffix_slowest_adapter"],
                        cold_first_suffix_slowest=cold["suffix_slowest_adapter"])
            for key in ("suffix_hot_p95_ms", "suffix_cold_p95_ms"):
                pair[f"{key}_delta"] = cold[key] - hot[key]
        pairs.append(pair)
    return results, pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    runs, pairs = compare_orders(root)
    write_csv(root / "arrival-order-runs.csv", runs)
    write_csv(root / "arrival-order-pairs.csv", pairs)
    print(f"{len(runs)} verified traces, {len(pairs)} fixed-capacity order pairs")


if __name__ == "__main__":
    main()
