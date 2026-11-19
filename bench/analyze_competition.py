"""Match a B1 miss to an actual B2 handoff for the same trace request."""
import argparse
import csv
import json
from pathlib import Path
import re

from bench.analyze_g1 import read_jsonl


def load(directory, scenario):
    clients = read_jsonl(directory / scenario / "client.jsonl")
    by_id = {f"cmpl-{row['request_id']}": row for row in clients}
    events = {}
    for event in read_jsonl(directory / "events.jsonl"):
        rid = event.get("target_id", event.get("request_id", ""))
        public_id = re.sub(r"-0-[0-9a-f]+$", "", rid)
        if public_id in by_id:
            clients_row = by_id[public_id]
            events.setdefault(clients_row["index"], []).append(event)
    return {row["index"]: row for row in clients}, events, by_id


def queue_ms(events):
    queued = next(e for e in events if e["event"] == "queued")
    admit = next(e for e in events if e["event"] == "admit")
    return (admit["time_ns"] - queued["time_ns"]) / 1e6


def handoff(events):
    attempt = None
    for event in events:
        if event["event"] == "handoff_attempt":
            attempt = event
        elif event["event"] == "target_admitted" and attempt is not None:
            return True
        elif event["event"] == "reservation_closed":
            attempt = None
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    rows = []
    for seed in config["seeds"]:
        for scenario, parameters in config["scenarios"].items():
            pair = root / str(seed)
            b1, e1, b1_ids = load(pair / "B1", scenario)
            b2, e2, _ = load(pair / "B2", scenario)
            if set(b1) != set(b2):
                raise ValueError("Unpaired client indices")
            for index, request in sorted(b1.items()):
                if request["model"] not in parameters["cold"]:
                    continue
                if request["model"] != b2[index]["model"]:
                    raise ValueError("Unpaired adapter")
                chain1, chain2 = e1[index], e2[index]
                misses = [event for event in chain1 if event["event"] == "slot_taken"]
                winners = [b1_ids[re.sub(r"-0-[0-9a-f]+$", "", event["request_id"])]
                           for event in misses]
                ms1, ms2 = queue_ms(chain1), queue_ms(chain2)
                rows.append({"seed": seed, "scenario": scenario, "request_index": index,
                             "offset_s": request["offset_s"], "model": request["model"],
                             "b1_missed_slots": len(misses),
                             "b1_winners": ",".join(f"{r['index']}:{r['model']}" for r in winners),
                             "b2_successful_handoff": handoff(chain2),
                             "b1_queue_ms": ms1, "b2_queue_ms": ms2, "delta_ms": ms2-ms1})
    with (root / "competition-requests.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    matching = [row for row in rows if row["b1_missed_slots"] and row["b2_successful_handoff"]]
    print(f"{len(rows)} cold requests paired; "
          f"{sum(bool(row['b1_missed_slots']) for row in rows)} B1 misses; "
          f"{len(matching)} corresponding successful B2 handoffs")
    for row in matching:
        print(row["seed"], row["request_index"], row["model"], row["b1_winners"],
              f"{row['b1_queue_ms']:.1f} -> {row['b2_queue_ms']:.1f} ms")


if __name__ == "__main__":
    main()
