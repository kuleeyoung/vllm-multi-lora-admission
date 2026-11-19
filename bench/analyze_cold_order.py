"""Explain each burst's reservations and compare mirrored cold-arrival roles."""
import argparse
import csv
import json
from pathlib import Path
import statistics

from bench.analyze_competition import handoff, load, queue_ms


SCENARIO = "queued-hot-bursts"


def waves(root, seed, variant):
    original, baseline, _ = load(root / str(seed) / "B1", SCENARIO)
    replay, observed, _ = load(root / str(seed) / "B2", SCENARIO)
    if set(original) != set(replay):
        raise ValueError("Unpaired requests")
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    burst = config["scenarios"][SCENARIO]["bursts"]
    hot_wave = 2 * burst["hot_pairs"] + len(burst["cold_offsets_s"])
    for start in range(0, len(original), hot_wave):
        indexes = range(start, start + hot_wave)
        first, second = [i for i in indexes if replay[i]["model"] in "CD"]
        sequence = sorted(
            (event["time_ns"], i) for i in indexes for event in observed[i]
            if event["event"] == "drain_started"
        )
        yield {
            "variant": variant, "seed": seed, "wave": start // hot_wave + 1,
            "early_cold": replay[first]["model"], "late_cold": replay[second]["model"],
            "b2_drain_targets": " -> ".join(replay[i]["model"] for _, i in sequence),
            "early_b1_missed": any(e["event"] == "slot_taken" for e in baseline[first]),
            "early_b2_handoff": handoff(observed[first]),
            "late_b2_handoff": handoff(observed[second]),
            "early_b1_ms": queue_ms(baseline[first]), "early_b2_ms": queue_ms(observed[first]),
            "late_b1_ms": queue_ms(baseline[second]), "late_b2_ms": queue_ms(observed[second]),
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("reference", type=Path)
    p.add_argument("swapped", type=Path)
    args = p.parse_args()
    trajectory = Path("2063/B1") / SCENARIO / "trajectory.json"
    reference = json.loads((args.reference / trajectory).read_text(encoding="utf-8"))
    swapped = json.loads((args.swapped / trajectory).read_text(encoding="utf-8"))
    swap = {"C": "D", "D": "C"}
    if [{**row, "model": swap.get(row["model"], row["model"])} for row in reference] != swapped:
        raise ValueError("Diagnostic trajectory changed fields other than the C/D adapter names")
    rows = [row for seed in (2063, 3191, 4787) for row in waves(args.reference, seed, "original")]
    rows.extend(waves(args.swapped, 2063, "swapped"))
    output = args.swapped / "cold-order-waves.csv"
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for variant in ("original", "swapped"):
        group = [r for r in rows if r["variant"] == variant]
        print(variant, len(group), "waves",
              "drain paths:", [r["b2_drain_targets"] for r in group])
        for role in ("early", "late"):
            delta = statistics.median(r[f"{role}_b2_ms"] - r[f"{role}_b1_ms"] for r in group)
            print(role, "B2 handoffs:", sum(r[f"{role}_b2_handoff"] for r in group),
                  "median queue delta (ms):", round(delta, 1))


if __name__ == "__main__":
    main()
