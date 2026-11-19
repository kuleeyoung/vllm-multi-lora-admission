"""Join paired capacity metrics to observed third-slot transitions."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import median

from bench.analyze_g3 import write_csv


def run_key(row):
    return row["scenario"], int(row["seed"]), row["mode"]


def compare_capacity(root):
    summary = json.loads((root / "summary.json").read_bytes())
    runs = {run_key(row): row for row in summary["runs"]}
    with (root / "capacity-budget.csv").open(encoding="utf-8", newline="") as source:
        kv_tokens = {run_key(row): int(row["kv_cache_tokens"]) for row in csv.DictReader(source)}
    transitions = Counter()
    events = root / "third-slot-admissions.csv"
    if events.exists():
        with events.open(encoding="utf-8", newline="") as source:
            transitions.update(run_key(row) for row in csv.DictReader(source))

    comparisons = []
    for pair in summary["pairs"]:
        scenario, seed = pair["scenario"], pair["seed"]
        # Pair labels are stored as candidate/base.
        candidate, base = pair["comparison"].split("/")
        l2, l3 = (scenario, seed, base), (scenario, seed, candidate)
        baseline, expanded = runs[l2], runs[l3]
        uses = transitions[l3]
        if (baseline["max_loras"], expanded["max_loras"]) != (2, 3):
            raise ValueError(f"Expected an L2/L3 comparison for {scenario}/{seed}")
        if transitions[l2] or bool(uses) != pair["capacity_exercised"]:
            raise ValueError(f"Inconsistent third-slot evidence for {scenario}/{seed}")
        failures = sum(row["groups"]["all"]["failed"] for row in (baseline, expanded))
        no_admit = sum(row["groups"]["all"]["no_admit"] for row in (baseline, expanded))
        preemptions = baseline["preemptions"] + expanded["preemptions"]
        if failures or no_admit or preemptions:
            raise ValueError(f"Incomplete or preempted capacity pair for {scenario}/{seed}: "
                             f"{failures=}, {no_admit=}, {preemptions=}")
        comparisons.append({
            "scenario": scenario, "seed": seed,
            "cold_requests_per_mode": baseline["groups"]["cold"]["requests"],
            "third_slot_transitions": uses,
            "l2_cold_p95_ms": baseline["groups"]["cold"]["queue_p95_ms"],
            "l3_cold_p95_ms": expanded["groups"]["cold"]["queue_p95_ms"],
            "cold_p95_delta_ms": pair["cold_p95_delta_ms"],
            "cold_p95_reduction_pct": pair["cold_p95_reduction_pct"],
            "hot_p95_delta_ms": pair["hot_p95_delta_ms"],
            "l2_goodput_rps": baseline["goodput_rps"],
            "l3_goodput_rps": expanded["goodput_rps"],
            "goodput_loss_pct": pair["goodput_loss_pct"],
            "goodput_delta_rps": pair["goodput_delta_rps"],
            "kv_delta_tokens": kv_tokens[l3] - kv_tokens[l2],
            "meets_targets": pair["meets_targets"],
        })
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    rows = compare_capacity(root)
    write_csv(root / "capacity-boundary-pairs.csv", rows)
    for scenario in dict.fromkeys(row["scenario"] for row in rows):
        pairs = [row for row in rows if row["scenario"] == scenario]
        exercised = sum(row["third_slot_transitions"] > 0 for row in pairs)
        passed = sum(row["meets_targets"] for row in pairs)
        goodput = median(row["goodput_delta_rps"] for row in pairs)
        print(f"{scenario}: exercised {exercised}/{len(pairs)}, "
              f"passed {passed}/{len(pairs)}, median Goodput delta {goodput:+.3f} rps")


if __name__ == "__main__":
    main()
