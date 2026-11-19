"""Recover the oldest queued hot request at each B3 guard decision."""
import argparse
import json
from pathlib import Path

from bench.analyze_g1 import read_jsonl
from bench.analyze_g3 import write_csv


def decisions(events, run_id, cold):
    prefix = f"cmpl-g3-{run_id}-"
    waiting = {}
    active_decisions = {"cold_followup_selected", "hot_guard_kept_order"}
    for event in sorted(events, key=lambda row: row["time_ns"]):
        kind = event["event"]
        rid = event.get("request_id", "")
        if kind == "queued" and rid.startswith(prefix):
            waiting[rid] = event
        elif kind in {"admit", "finished"} and rid.startswith(prefix):
            waiting.pop(rid, None)
        elif kind == "preempted" and rid.startswith(prefix):
            raise ValueError("Guard age reconstruction requires a run without preemption")
        if kind in active_decisions and event["target_id"].startswith(prefix):
            hot = min((row for row in waiting.values() if row["adapter"] not in cold),
                      key=lambda row: row["time_ns"], default=None)
            yield {"decision": kind, "target_id": event["target_id"],
                   "oldest_hot_id": hot["request_id"] if hot else "",
                   "oldest_hot_wait_ms": (event["time_ns"] - hot["time_ns"]) / 1e6 if hot else None}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    rows = []
    for seed in config["seeds"]:
        for mode in config["modes"]:
            directory = root / str(seed) / mode
            events = read_jsonl(directory / "events.jsonl")
            for scenario, params in config["scenarios"].items():
                run = json.loads((directory / scenario / "run.json").read_text(encoding="utf-8"))
                rows.extend({"seed": seed, "mode": mode, "scenario": scenario, **row}
                            for row in decisions(events, run["run_id"], params["cold"]))
    if rows:
        write_csv(root / "guard-decisions.csv", rows)
    print(f"{len(rows)} guard decisions linked to queued hot requests")


if __name__ == "__main__":
    main()
