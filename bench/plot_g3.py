"""Plot paired run summaries with Matplotlib."""
import argparse
import json
from pathlib import Path
from statistics import median

import matplotlib.pyplot as plt

from bench.analyze_competition import load
from bench.analyze_arrival_order import ORDERS


def plot_prefix_timeline(root, config):
    seed = config["seeds"][0]
    modes = config["modes"]
    colors = {"A": "#235a97", "B": "#338477", "C": "#d07431", "D": "#914881"}
    fig, axes = plt.subplots(len(modes), len(ORDERS), figsize=(11, 7.5),
                             sharex=True, sharey=True, squeeze=False)
    for row, mode in zip(axes, modes):
        directory = root / str(seed) / mode
        for ax, order in zip(row, ORDERS):
            run = json.loads((directory / order / "run.json").read_bytes())
            clients, chains, _ = load(directory, order)
            for adapter, color in colors.items():
                intervals = []
                for index, request in clients.items():
                    if request["model"] != adapter:
                        continue
                    chain = chains[index]
                    queued = next(e["time_ns"] for e in chain if e["event"] == "queued")
                    admitted = next(e["time_ns"] for e in chain if e["event"] == "admit")
                    intervals.append((index + 1, queued / 1e9 - run["start_s"],
                                      admitted / 1e9 - run["start_s"]))
                indices, starts, ends = zip(*intervals)
                ax.hlines(indices, starts, ends, color=color, alpha=0.75)
                ax.scatter(ends, indices, s=9, color=color, label=adapter)
            ax.axhspan(0.5, config["shared_suffix_from_index"] + 0.5, color="#edf0f4", zorder=0)
            ax.set_title(f"{mode} · {order}")
            ax.grid(axis="x", alpha=0.2)
        row[0].set_ylabel("Request index")
    axes[0, 0].invert_yaxis()
    axes[0, 0].set_yticks((1, 16, 32, 48, 64))
    fig.supxlabel("Seconds since replay start")
    fig.suptitle(f"Seed {seed} · EngineCore queue intervals (shaded rows: experimental prefix)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center right", title="LoRA", frameon=False)
    fig.tight_layout(rect=(0, 0, 0.94, 0.95))
    fig.savefig(root / "prefix-admission-timeline.png", dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory
    report = json.loads((root / "summary.json").read_text())
    runs = report["runs"]
    scenarios = list(dict.fromkeys(r["scenario"] for r in runs))
    modes = list(dict.fromkeys(r["mode"] for r in runs))
    colors = {"B0": "#61748a", "B1": "#b65c25", "B2": "#126c61", "B3": "#6743a5",
              "B3-4s": "#6743a5", "B3-5s": "#4178ad", "B3-6s": "#17777d",
              "B0-L2": "#61748a", "B0-L3": "#126c61"}
    figures = [
        ("cold-p95.png", "Cold cohort queue P95 (ms)",
         lambda r: r["groups"]["cold"]["queue_p95_ms"]),
        ("hot-p95.png", "Hot cohort queue P95 (ms)",
         lambda r: r["groups"]["hot"]["queue_p95_ms"]),
        ("goodput.png", "Goodput (requests/s)", lambda r: r["goodput_rps"]),
    ]
    for filename, label, extract in figures:
        fig, grid = plt.subplots(1, len(scenarios), figsize=(max(4, 3.25 * len(scenarios)), 4),
                                 sharey=True, squeeze=False)
        axes = grid[0]
        for ax, scenario in zip(axes, scenarios):
            values = [[extract(r) for r in runs if r["scenario"] == scenario and r["mode"] == mode]
                      for mode in modes]
            for seed_values in zip(*values):
                ax.plot(range(len(modes)), seed_values, color="#aeb7c1", linewidth=1, zorder=1)
            for position, (mode, samples) in enumerate(zip(modes, values)):
                color = colors[mode]
                observed = [sample for sample in samples if sample is not None]
                if observed:
                    ax.scatter([position] * len(observed), observed, color=color, alpha=0.65, zorder=2)
                    ax.scatter(position, median(observed), color=color, marker="_", s=360, zorder=3)
            ax.set_title(scenario.replace("-", "\n", 1))
            ax.set_xticks(range(len(modes)), modes)
            ax.grid(axis="y", alpha=0.2)
        axes[0].set_ylabel(label)
        seed_count = len({row["seed"] for row in runs})
        fig.suptitle(f"Paired seeds per scenario: {seed_count} | Horizontal bars: medians")
        fig.tight_layout()
        fig.savefig(root / filename, dpi=180)
        plt.close(fig)
    config_path = root / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_bytes())
        if config.get("shared_suffix_from_index") is not None:
            plot_prefix_timeline(root, config)


if __name__ == "__main__":
    main()
