"""Replay fixed arrival offsets and retain client times and request IDs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
import urllib.request

from bench.smoke import parse_stream


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("configs/g1.json"))
    p.add_argument("--url", default="http://127.0.0.1:8018/v1/completions")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--run", required=True)
    args = p.parse_args()
    config = json.loads(args.config.read_text())
    requests = [(i * config["hot_interval_s"], name, config["hot_max_tokens"])
                for i in range(config["hot_pairs"]) for name in "AB"]
    requests += [(offset, name, config["cold_max_tokens"])
                 for name, offset in config["cold_arrivals_s"].items()]
    trajectory = sorted(requests)
    digest = hashlib.sha256(json.dumps([config["prompt"], trajectory]).encode()).hexdigest()
    ready = threading.Barrier(len(trajectory) + 1)

    def send(index, offset, name, max_tokens):
        rid = f"g1-{args.run}-{index:03}-{name}"
        payload = {"model": name, "prompt": config["prompt"], "max_tokens": max_tokens,
                   "ignore_eos": True, "temperature": 0, "stream": True}
        req = urllib.request.Request(args.url, data=json.dumps(payload).encode(),
              headers={"Content-Type": "application/json", "X-Request-Id": rid})
        ready.wait(timeout=10)
        planned = start + offset
        time.sleep(max(0, planned - time.monotonic()))
        sent = time.monotonic()
        row = {"request_id": rid, "adapter": name, "offset_s": offset,
               "send_lag_s": sent - planned, "sent_monotonic_s": sent,
               "trajectory_sha256": digest, "max_tokens": max_tokens}
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                _, first, _ = parse_stream(response)
            row.update(status="ok", ttft_s=first - sent)
        except (OSError, ValueError) as exc:
            row.update(status="error", error=str(exc))
        row["elapsed_s"] = time.monotonic() - sent
        return row

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ok = True
    with args.output.open("w", encoding="utf-8") as output, ThreadPoolExecutor(len(trajectory)) as pool:
        futures = [pool.submit(send, index, *request) for index, request in enumerate(trajectory)]
        start = time.monotonic() + 0.3
        ready.wait(timeout=10)
        for future in as_completed(futures):
            row = future.result()
            output.write(json.dumps(row) + "\n")
            output.flush()
            ok &= row["status"] == "ok"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
