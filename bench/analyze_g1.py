"""Join B0 replay records to scheduler events and validate each causal chain."""
import argparse
import json
from pathlib import Path
import re


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--clients", required=True, type=Path, nargs="+")
    parser.add_argument("--limit", required=True, type=int, choices=[2, 4])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    events = read_jsonl(args.events)
    loaded = {r["pid"]: r["source"] for r in events if r["event"] == "scheduler_loaded"}
    runs = []
    for path in args.clients:
        clients = read_jsonl(path)
        if not clients or len({c["request_id"] for c in clients}) != len(clients):
            raise SystemExit(f"Expected unique client requests in {path}")
        joined = {}
        for client in clients:
            rid = client["request_id"]
            pattern = re.compile(rf"cmpl-{re.escape(rid)}-0-[0-9a-f]+")
            chain = sorted((e for e in events if pattern.fullmatch(e.get("request_id", ""))),
                           key=lambda e: e["time_ns"])
            if (client["status"] != "ok" or len({e["request_id"] for e in chain}) != 1
                    or any(e["adapter"] != client["adapter"] or e["pid"] not in loaded for e in chain)):
                raise SystemExit(f"Missing or inconsistent client/server evidence: {rid}")
            joined[rid] = chain
        hot = [e for c in clients if c["adapter"] in "AB" for e in joined[c["request_id"]]
               if e["event"] == "admit"]
        cold = {}
        for client in clients:
            name = client["adapter"]
            if name not in ("C", "D"):
                continue
            chain = joined[client["request_id"]]
            queued = next(e for e in chain if e["event"] == "queued")
            admit = next(e for e in chain if e["event"] == "admit")
            finish = next(e for e in chain if e["event"] == "finished")
            if not queued["time_ns"] < admit["time_ns"] < finish["time_ns"]:
                raise SystemExit(f"Invalid event order for {client['request_id']}")
            skips = [e for e in chain if e["event"] == "skip_lora"
                     and queued["time_ns"] <= e["time_ns"] < admit["time_ns"]]
            first_skip = skips[0] if skips else None
            overtakes = [e for e in hot if first_skip and
                         first_skip["time_ns"] < e["time_ns"] < admit["time_ns"]]
            both_hot_running = bool(first_skip and all(any(
                event["request_id"] in first_skip["running"] and event["adapter"] == adapter
                for event in hot)
                for adapter in "AB"))
            cold[name] = {"queue_ms": (admit["time_ns"] - queued["time_ns"]) / 1e6,
                          "skip_count": len(skips), "first_skip": first_skip,
                          "both_hot_running_at_first_skip": both_hot_running,
                          "hot_admissions_after_first_skip": overtakes,
                          "queued": queued, "admit": admit, "finish": finish}
        c = cold["C"]
        full_skip = all(e["limit"] == args.limit and len(e["active"]) == args.limit
                        for chain in joined.values() for e in chain if e["event"] == "skip_lora")
        passed = full_skip and (bool(c["skip_count"] and c["both_hot_running_at_first_skip"]
                                       and c["hot_admissions_after_first_skip"])
                                if args.limit == 2 else all(not row["skip_count"] for row in cold.values()))
        runs.append({"client_file": path.name, "requests": len(clients),
                     "trajectory_sha256": clients[0]["trajectory_sha256"],
                     "max_send_lag_ms": max(c["send_lag_s"] for c in clients) * 1000,
                     "cold": cold, "passed": passed})
    report = {"limit": args.limit, "runs": runs,
              "passed": all(r["passed"] for r in runs)
              and len({r["trajectory_sha256"] for r in runs}) == 1}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for r in runs:
        print(r["client_file"], r["passed"],
              {n: (round(v["queue_ms"], 1), v["skip_count"]) for n, v in r["cold"].items()})
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
