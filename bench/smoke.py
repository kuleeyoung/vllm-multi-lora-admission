"""Sequential and concurrent streaming checks against an existing vLLM server.

These checks verify transport and requested model names, not numerical LoRA binding.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import urllib.request
import uuid


def parse_stream(response):
    text = []
    first = None
    chunks = 0
    done = False
    for raw in response:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            done = True
            break
        event = json.loads(payload)
        if "error" in event:
            raise ValueError(str(event["error"]))
        for choice in event.get("choices", []):
            content = choice.get("text", "")
            if content:
                if first is None:
                    first = time.perf_counter()
                chunks += 1
                text.append(content)
    if not done or first is None:
        raise ValueError("Incomplete stream or no generated text")
    return "".join(text), first, chunks


def request(base_url, model, phase, timeout, max_tokens=32):
    rid = f"g0-{uuid.uuid4().hex}"
    start = time.perf_counter()
    row = {"request_id": rid, "requested_model": model, "phase": phase,
           "sent_monotonic_s": start, "adapter_binding_verified": False}
    body = {"model": model, "prompt": "Continue the sequence: one, two, three,",
            "max_tokens": max_tokens, "temperature": 0, "stream": True}
    row["max_tokens"] = max_tokens
    req = urllib.request.Request(base_url.rstrip("/") + "/completions",
          data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Request-Id": rid})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content, first, chunks = parse_stream(response)
        row.update(status="ok", text=content, ttft_s=first-start, text_chunks=chunks)
    except Exception as e:
        row.update(status="error", error=str(e))
    row["elapsed_s"] = time.perf_counter() - start
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    p.add_argument("--base-model", required=True)
    p.add_argument("--adapters", nargs=4, default=["A", "B", "C", "D"])
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--max-tokens", type=int, default=32)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if args.max_tokens < 1:
        p.error("--max-tokens must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.output.open("w", encoding="utf-8") as f:
        def save(row):
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
        for model in [args.base_model, *args.adapters]:
            save(request(args.base_url, model, "sequential", args.timeout, args.max_tokens))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(request, args.base_url, model, "concurrent", args.timeout, args.max_tokens)
                       for model in args.adapters]
            for future in futures:
                save(future.result())
    print(f"{sum(r['status'] == 'ok' for r in rows)}/{len(rows)} streams passed. "
          "Use bench.check_binding to compare adapter outputs.")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
