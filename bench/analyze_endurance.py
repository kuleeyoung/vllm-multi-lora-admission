"""Summarize repeated serving windows and post-warmup resource samples."""
import argparse
import csv
import json
from pathlib import Path


def span(values):
    return {"first": values[0], "last": values[-1], "min": min(values), "max": max(values),
            "last_minus_first": values[-1] - values[0]}


def plot(root, samples):
    import matplotlib.pyplot as plt

    time = [float(row["after_monotonic_s"]) for row in samples]
    elapsed = [value - time[0] for value in time]
    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    for metric, label in (("server_rss_kib", "API server"), ("engine_rss_kib", "EngineCore")):
        axes[0].plot(elapsed, [int(row[metric]) / 1024 for row in samples], "o-", label=label)
    axes[0].set_ylabel("Process RSS (MiB)")
    axes[0].legend(loc="best")
    for metric, label in (("server_fd_count", "API server"), ("engine_fd_count", "EngineCore")):
        axes[1].plot(elapsed, [int(row[metric]) for row in samples], "o-", label=label)
    axes[1].set_ylabel("Open descriptors")
    axes[1].legend(loc="best")
    axes[2].plot(elapsed, [int(row["gpu_used_mib"]) for row in samples], "o-", color="#126c61")
    axes[2].set_ylabel("Device GPU used (MiB)")
    axes[2].set_xlabel("Seconds since startup sample")
    for ax in axes:
        ax.axvline(elapsed[1], color="#8996a3", linestyle="--", linewidth=1)
        ax.grid(alpha=0.25)
    fig.suptitle("B0 with three LoRA slots: idle samples (dashed: first cycle complete)")
    fig.tight_layout()
    fig.savefig(root / "idle-resources.png", dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--plot", action="store_true")
    args = p.parse_args()
    root = args.directory
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    with (root / "idle-samples.csv").open(encoding="utf-8", newline="") as source:
        samples = [row for row in csv.DictReader(source) if row["profile"] == "recommended"]
    if len(samples) < 2 or samples[0]["moment"] != "startup":
        raise ValueError("Expected startup and at least one completed recommended cycle")
    post_warmup = samples[1:]
    fields = ("gpu_used_mib", "server_rss_kib", "engine_rss_kib", "server_fd_count", "engine_fd_count")
    results = {"cycles": len(post_warmup),
               "elapsed_s": float(samples[-1]["after_monotonic_s"]) - float(samples[0]["after_monotonic_s"]),
               "post_first_cycle": {key: span([int(row[key]) for row in post_warmup]) for key in fields},
               "windows": {},
               "shutdown_resources": summary["shutdown_resources"]}
    for window in summary["windows"]:
        if window["profile"] == "recommended":
            results["windows"].setdefault(window["scenario"], []).append(window)
    results["windows"] = {
        label: {"requests": sum(row["requests"] for row in rows),
                "good_per_window": span([row["good"] for row in rows]),
                "ttft_p95_s": span([row["ttft_p95_s"] for row in rows]),
                "tpot_p95_s": span([row["tpot_p95_s"] for row in rows])}
        for label, rows in results["windows"].items()
    }
    (root / "endurance-trends.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if args.plot:
        plot(root, samples)
    print(f"{results['cycles']} cycles in {results['elapsed_s']:.1f} seconds")
    for key, values in results["post_first_cycle"].items():
        print(key, values)


if __name__ == "__main__":
    main()
