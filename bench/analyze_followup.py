"""Join each optional B3 selection to the corresponding actual admission."""
import argparse
import json
from pathlib import Path

from bench.analyze_competition import load, queue_ms
from bench.analyze_g3 import write_csv


def successful_after_selection(events):
    selected = attempted = False
    for event in events:
        if event["event"] == "cold_followup_selected":
            selected = True
        elif event["event"] == "handoff_attempt" and selected:
            attempted = True
        elif event["event"] == "target_admitted" and attempted:
            return True
        elif event["event"] == "reservation_closed":
            selected = attempted = False
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    base_mode, candidate_mode = config["modes"]
    rows = []
    for seed in config["seeds"]:
        for scenario, parameters in config["scenarios"].items():
            pair = root / str(seed)
            baseline, first, _ = load(pair / base_mode, scenario)
            candidate, second, _ = load(pair / candidate_mode, scenario)
            if set(baseline) != set(candidate):
                raise ValueError("Unpaired trajectory indices")
            size = 2 * parameters["bursts"]["hot_pairs"] + len(parameters["cold"])
            for index in sorted(baseline):
                row = baseline[index]
                if row["model"] != candidate[index]["model"]:
                    raise ValueError("Unpaired adapter")
                if row["model"] not in parameters["cold"]:
                    continue
                base_ms, candidate_ms = queue_ms(first[index]), queue_ms(second[index])
                selected = any(e["event"] == "cold_followup_selected" for e in second[index])
                rows.append({"seed": seed, "scenario": scenario, "wave": index // size + 1,
                             "index": index, "model": row["model"],
                             "baseline_followup_admitted": successful_after_selection(first[index]),
                             "followup_selected": selected,
                             "followup_admitted": successful_after_selection(second[index]),
                             f"{base_mode.lower()}_queue_ms": base_ms,
                             f"{candidate_mode.lower()}_queue_ms": candidate_ms,
                             "delta_ms": candidate_ms - base_ms})
    write_csv(root / "followup-requests.csv", rows)
    print("Successful follow-up admissions:",
          f"{base_mode}={sum(r['baseline_followup_admitted'] for r in rows)}",
          f"{candidate_mode}={sum(r['followup_admitted'] for r in rows)}")
    for row in rows:
        if row["followup_selected"]:
            print(row["seed"], row["wave"], row["model"], row["followup_admitted"],
                  f"{row[f'{base_mode.lower()}_queue_ms']:.1f} -> "
                  f"{row[f'{candidate_mode.lower()}_queue_ms']:.1f} ms")


if __name__ == "__main__":
    main()
