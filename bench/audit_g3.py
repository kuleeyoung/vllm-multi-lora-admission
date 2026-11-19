"""Recompute the archived G3 tables from raw inputs without starting vLLM."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from bench.analyze_g3 import MODES


CORE = ("bench.analyze_g3", ("summary.json", "pairs.csv", "runs.csv", "cohorts.csv"))
CAPACITY = ("bench.analyze_capacity", ("capacity-budget.csv", "third-slot-admissions.csv"))
BOUNDARY = ("bench.analyze_capacity_boundary", ("capacity-boundary-pairs.csv",))
ORDER = ("bench.analyze_arrival_order", ("arrival-order-runs.csv", "arrival-order-pairs.csv"))
SUITES = {
    "paired-01": (CORE,),
    "clean-01": (CORE,),
    "guard-midpoint-01": (
        CORE,
        ("bench.analyze_followup", ("followup-requests.csv",)),
        ("bench.analyze_guard_decisions", ("guard-decisions.csv",)),
    ),
    "decision-matrix-01": (
        CORE,
        ("bench.analyze_decision_matrix", ("decision-comparisons.csv", "decision-modes.csv")),
        CAPACITY,
    ),
    "capacity-boundary-01": (
        CORE, ("bench.analyze_decision_matrix", ("decision-comparisons.csv", "decision-modes.csv")),
        CAPACITY, BOUNDARY,
    ),
    "arrival-order-01": (CORE, CAPACITY, BOUNDARY, ORDER),
    "prefix-order-01": (CORE, CAPACITY, BOUNDARY, ORDER),
}
CAPACITY_FIELDS = {"max_loras", "peak_active_loras_observed"}
LEGACY_SUITES = {"paired-01", "clean-01", "guard-midpoint-01"}


def input_paths(source, suite):
    yield Path("config.json")
    config = json.loads((source / "config.json").read_bytes())
    for seed in config["seeds"]:
        for mode in config.get("modes", MODES):
            run = Path(str(seed)) / mode
            yield run / "events.jsonl"
            if CAPACITY in SUITES[suite]:
                yield run / "server.log"
            for scenario in config["scenarios"]:
                for name in ("run.json", "trajectory.json", "client.jsonl", "gpu.jsonl"):
                    yield run / scenario / name


def stage_inputs(source, staged, suite):
    for path in input_paths(source, suite):
        target = staged / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / path, target)


def matches(archived, rebuilt, *, legacy):
    if archived.suffix == ".json":
        expected, actual = (json.loads(path.read_bytes()) for path in (archived, rebuilt))
        if legacy:
            for row in actual["runs"]:
                for field in CAPACITY_FIELDS:
                    del row[field]
        return actual == expected

    with archived.open(encoding="utf-8", newline="") as original, \
            rebuilt.open(encoding="utf-8", newline="") as generated:
        expected, actual = csv.DictReader(original), csv.DictReader(generated)
        expected_fields, actual_fields = set(expected.fieldnames), set(actual.fieldnames)
        if len(expected_fields) != len(expected.fieldnames) or len(actual_fields) != len(actual.fieldnames):
            return False
        rows = list(actual)
        if legacy and archived.name == "runs.csv":
            actual_fields -= CAPACITY_FIELDS
            for row in rows:
                for field in CAPACITY_FIELDS:
                    del row[field]
        return expected_fields == actual_fields and list(expected) == rows


def audit(source, suite):
    with TemporaryDirectory(prefix="g3-audit-") as temporary:
        staged = Path(temporary)
        stage_inputs(source, staged, suite)
        outputs = []
        for module, names in SUITES[suite]:
            result = subprocess.run([sys.executable, "-m", module, str(staged)],
                                    capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                raise ValueError(f"{module} failed for {source}:\n{result.stderr or result.stdout}")
            for name in names:
                if not matches(source / name, staged / name, legacy=suite in LEGACY_SUITES):
                    raise ValueError(f"Recomputed output differs from {source / name}")
                outputs.append(name)
        summary = json.loads((staged / "summary.json").read_bytes())
        runs = summary["runs"]
        requests = sum(run["groups"]["all"]["requests"] for run in runs)
        print(f"{source.name}: {len(outputs)} tables match, {len(runs)} runs, {requests} requests")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing the archived G3 runs")
    parser.add_argument("--suite", choices=SUITES, action="append", help="Audit selected archives only")
    args = parser.parse_args()
    try:
        for suite in args.suite or SUITES:
            audit(args.root / suite, suite)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"G3 audit failed: {error}\n")


if __name__ == "__main__":
    main()
