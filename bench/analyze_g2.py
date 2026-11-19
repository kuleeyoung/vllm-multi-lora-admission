"""Validate paired policy traces and write a compact diagnostic report."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from bench.analyze_g1 import read_jsonl


def summarize(root, mode):
    clients = read_jsonl(root / f"{mode}-client.jsonl")
    events = read_jsonl(root / f"{mode}-events.jsonl")
    binding = json.loads((root / f"{mode}-binding.json").read_text())
    loaded = {e["pid"] for e in events if e["event"] == "scheduler_loaded" and e["mode"] == mode}
    if (len(clients) != len({c["request_id"] for c in clients})
            or not clients or not binding["binding_passed"]):
        raise ValueError(f"Incomplete requests or failed binding for {mode}")
    cold = {}
    waits = {}
    for client in clients:
        pattern = re.compile(rf"cmpl-{re.escape(client['request_id'])}-0-[0-9a-f]+")
        chain = [e for e in events if "adapter" in e and pattern.fullmatch(e.get("request_id", ""))]
        counts = Counter(e["event"] for e in chain)
        if (client["status"] != "ok" or any(e["pid"] not in loaded
                or e["adapter"] != client["adapter"] for e in chain)
                or any(counts[event] != 1 for event in ("queued", "admit", "finished"))
                or counts["preempted"]):
            raise ValueError(f"Unexpected lifecycle for {client['request_id']}: {counts}")
        queued, admit, finish = [next(e for e in chain if e["event"] == name)
                                 for name in ("queued", "admit", "finished")]
        adapter_id = "ABCD".index(client["adapter"]) + 1
        if (not queued["time_ns"] < admit["time_ns"] < finish["time_ns"]
                or len(set(admit["active_before"]) | {adapter_id}) > 2):
            raise ValueError(f"Invalid lifecycle order for {client['request_id']}")
        wait = (admit["time_ns"] - queued["time_ns"]) / 1e6
        waits[queued["request_id"]] = wait
        if client["adapter"] in "CD":
            cold[client["adapter"]] = {"queue_ms": wait, "request_id": queued["request_id"],
                                       "skip_lora": counts["skip_lora"]}
    policy_events = [e for e in events if e.get("target_id") in waits]
    counts = Counter(e["event"] for e in policy_events)
    if mode == "B0" and (policy_events or any(e["event"] == "drain_deferred" for e in events)):
        raise ValueError("Unexpected policy activity in B0")
    if mode != "B0" and (not counts["drain_started"] or not counts["slot_released"]):
        raise ValueError(f"No completed drain in {mode}")
    if mode == "B2" and not any(
        e["event"] == "target_admitted" and any(
            earlier["event"] == "handoff_attempt" and earlier["target_id"] == e["target_id"]
            and earlier["time_ns"] < e["time_ns"] for earlier in policy_events
        ) for e in policy_events
    ):
        raise ValueError("No actual handoff admission")
    if mode == "B1" and counts["handoff_attempt"]:
        raise ValueError("B1 attempted a handoff")
    if counts["drain_started"] != counts["reservation_closed"]:
        raise ValueError(f"Unclosed reservation in {mode}")
    digests = {c["trajectory_sha256"] for c in clients}
    if len(digests) != 1:
        raise ValueError(f"Inconsistent workload digest in {mode}")
    return {"request_count": len(clients), "binding_passed": True,
            "binding_references": binding["sequential_outputs"],
            "trajectory_sha256": digests.pop(), "cold": cold,
            "policy_counts": dict(counts), "policy_events": policy_events}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory
    report = {mode: summarize(root, mode) for mode in ("B0", "B1", "B2")}
    if len({row["trajectory_sha256"] for row in report.values()}) != 1:
        raise ValueError("Expected the same fixed workload in all modes")
    if any(row["binding_references"] != report["B0"]["binding_references"] for row in report.values()):
        raise ValueError("Isolated adapter outputs differ across modes")
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for mode, row in report.items():
        print(mode, {name: round(c["queue_ms"], 1) for name, c in row["cold"].items()},
              row["policy_counts"])


if __name__ == "__main__":
    main()
