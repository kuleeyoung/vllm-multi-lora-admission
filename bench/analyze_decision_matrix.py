"""Summarize alternatives across independent workload scenarios."""
import argparse
import json
from pathlib import Path
from statistics import median

from bench.analyze_g3 import write_csv


def mid(rows, key):
    values = [row[key] for row in rows if row[key] is not None]
    return median(values) if values else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    results = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    pair_summary = []
    modes_summary = []
    for scenario in config["scenarios"]:
        for base, candidate in config["comparisons"]:
            label = f"{candidate}/{base}"
            pairs = [r for r in results["pairs"] if r["scenario"] == scenario and r["comparison"] == label]
            if len(pairs) != len(config["seeds"]):
                raise ValueError(f"Incomplete samples for {scenario}/{label}")
            losses = [r["goodput_loss_pct"] for r in pairs if r["goodput_loss_pct"] is not None]
            pair_summary.append({"scenario": scenario, "comparison": label,
                                 "pairs": len(pairs),
                                 "median_cold_p95_delta_ms": mid(pairs, "cold_p95_delta_ms"),
                                 "median_cold_p95_reduction_pct": mid(pairs, "cold_p95_reduction_pct"),
                                 "median_hot_p95_delta_ms": mid(pairs, "hot_p95_delta_ms"),
                                 "median_goodput_loss_pct": mid(pairs, "goodput_loss_pct"),
                                 "worst_goodput_loss_pct": max(losses, default=None),
                                 "all_targets_met_pairs": sum(r["meets_targets"] for r in pairs)})
        for mode in config["modes"]:
            runs = [r for r in results["runs"] if r["scenario"] == scenario and r["mode"] == mode]
            modes_summary.append({
                "scenario": scenario, "mode": mode,
                "median_cold_p95_ms": mid([r["groups"]["cold"] for r in runs], "queue_p95_ms"),
                "median_hot_p95_ms": mid([r["groups"]["hot"] for r in runs], "queue_p95_ms"),
                "median_goodput_rps": mid(runs, "goodput_rps"),
                "median_busy_token_s": mid(runs, "burst_output_tokens_per_s"),
                "failed": sum(r["groups"]["all"]["failed"] for r in runs),
                "preemptions": sum(r["preemptions"] for r in runs),
            })
    write_csv(root / "decision-comparisons.csv", pair_summary)
    write_csv(root / "decision-modes.csv", modes_summary)


if __name__ == "__main__":
    main()
