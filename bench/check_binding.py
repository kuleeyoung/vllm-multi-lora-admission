"""Check whether distinct isolated outputs survive concurrent adapter requests."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--streams", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-model", default="Qwen/Qwen3-0.6B")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.streams.read_text(encoding="utf-8").splitlines()]
    adapters = list("ABCD")
    reference_models = [args.base_model, *adapters]
    expected = {(phase, model) for phase, models in [
        ("sequential", reference_models), ("concurrent", adapters)
    ] for model in models}
    by_key = {(r["phase"], r["requested_model"]): r for r in rows}
    if (len(rows) != len(expected) or set(by_key) != expected
            or len({r["request_id"] for r in rows}) != len(rows)
            or any(r["status"] != "ok" or not r.get("text") for r in rows)):
        raise SystemExit("Expected nine successful, distinct streams for the configured models")
    references = {model: by_key["sequential", model]["text"] for model in reference_models}
    matches = {name: by_key["concurrent", name]["text"] == references[name] for name in adapters}
    distinct = len(set(references.values())) == len(references)
    concurrent = [by_key["concurrent", name] for name in adapters]
    overlap = max(r["sent_monotonic_s"] for r in concurrent) < min(
        r["sent_monotonic_s"] + r["elapsed_s"] for r in concurrent
    )
    report = {"method": "exact generated text against isolated HTTP references",
              "binding_passed": distinct and overlap and all(matches.values()),
              "distinct_base_and_adapter_outputs": distinct,
              "client_request_intervals_all_overlap": overlap,
              "concurrent_matches": matches, "sequential_outputs": references}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["binding_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
