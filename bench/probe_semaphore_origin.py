"""Record semaphore registration call sites during an isolated no-inference launch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from bench.run_g3 import wait_health
from bench.validate_serving import shm_entries, verify_models


HOOK = '''
import json
import os
import traceback
from multiprocessing import resource_tracker


def observed(original, operation):
    def wrapped(name, kind):
        result = original(name, kind)
        if kind == "semaphore":
            site = [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in traceback.extract_stack(limit=18)[:-1]]
            row = {"pid": os.getpid(), "operation": operation, "name": name, "stack": site}
            fd = os.open(os.environ["LORA_SEMAPHORE_TRACE"], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (json.dumps(row) + "\\n").encode())
            finally:
                os.close(fd)
        return result
    return wrapped


resource_tracker.register = observed(resource_tracker.register, "register")
resource_tracker.unregister = observed(resource_tracker.unregister, "unregister")
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    root = p.parse_args().directory.resolve()
    root.mkdir(parents=True)
    overlay = root / "probe"
    overlay.mkdir()
    (overlay / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    trace = root / "semaphore-events.jsonl"
    base = "http://127.0.0.1:" + os.environ.get("LORA_PORT", "8018")
    try:
        with urllib.request.urlopen(base + "/health", timeout=1):
            raise RuntimeError(f"The serving port is already in use: {base}")
    except OSError:
        pass
    before = shm_entries()
    env = {**os.environ, "PYTHONPATH": str(overlay), "LORA_SEMAPHORE_TRACE": str(trace),
           "LORA_MAX_LORAS": "3"}
    log_path = root / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        service = subprocess.Popen(["bash", "scripts/serve_g0.sh"], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_health(service, base)
            verify_models(base)
            while_running = shm_entries()
        finally:
            if service.poll() is None:
                service.terminate()
            try:
                service.wait(timeout=30)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait()
    time.sleep(1)
    after = shm_entries()
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
    outstanding = {}
    for row in records:
        if row["operation"] == "register":
            outstanding[row["name"]] = row
        else:
            outstanding.pop(row["name"], None)
    report = {"requests": 0, "before_start": before, "while_running": while_running,
              "after_exit": after, "names_without_explicit_unregister": list(outstanding.values()),
              "warning_seen": "leaked semaphore objects" in log_path.read_text(encoding="utf-8")}
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Outstanding registration names:", ", ".join(outstanding))
    print("Entries added in /dev/shm after exit:", sorted(set(after) - set(before)))


if __name__ == "__main__":
    main()
