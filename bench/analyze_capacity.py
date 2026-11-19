"""Summarize actual use of a third LoRA slot and the startup KV budget."""
import argparse
import json
from pathlib import Path
import re

from bench.analyze_g1 import read_jsonl
from bench.analyze_g3 import write_csv


def startup_value(log, pattern):
    matches = re.findall(pattern, log)
    if len(matches) != 1:
        raise ValueError(f"Expected one startup value for {pattern}, got {matches}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    report = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    budget = []
    uses = []
    for row in report["runs"]:
        run = root / str(row["seed"]) / row["mode"]
        log = (run / "server.log").read_text(encoding="utf-8")
        kv_gib = float(startup_value(log, r"Available KV cache memory: ([\d.]+) GiB"))
        kv_tokens = int(startup_value(log, r"GPU KV cache size: ([\d,]+) tokens").replace(",", ""))
        budget.append({"seed": row["seed"], "mode": row["mode"], "scenario": row["scenario"],
                       "profiled_kv_gib": kv_gib, "kv_cache_tokens": kv_tokens,
                       "peak_gpu_mib_sampled": row["peak_gpu_mib_sampled"],
                       "burst_output_tokens_per_s": row["burst_output_tokens_per_s"]})
        manifest = json.loads((run / row["scenario"] / "run.json").read_text(encoding="utf-8"))
        prefix = f"cmpl-g3-{manifest['run_id']}-"
        for e in read_jsonl(run / "events.jsonl"):
            if e["event"] != "admit" or not e["request_id"].startswith(prefix):
                continue
            adapter_id = "ABCD".index(e["adapter"]) + 1
            if len(e["active_before"]) == 2 and adapter_id not in e["active_before"]:
                uses.append({"seed": row["seed"], "mode": row["mode"], "scenario": row["scenario"],
                             "request_id": e["request_id"], "adapter": e["adapter"],
                             "active_before": ",".join(map(str, e["active_before"])),
                             "admission_offset_s": e["time_ns"] / 1e9 - manifest["start_s"]})
    write_csv(root / "capacity-budget.csv", budget)
    if uses:
        write_csv(root / "third-slot-admissions.csv", uses)
    print(f"{len(uses)} admissions increased concurrent LoRA types from two to three")
    for row in budget:
        print(row["seed"], row["mode"], row["profiled_kv_gib"], row["kv_cache_tokens"],
              row["peak_gpu_mib_sampled"])


if __name__ == "__main__":
    main()
