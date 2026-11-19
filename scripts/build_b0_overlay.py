"""Build a hash-checked, import-only scheduler overlay for G1."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


HOOK = '''
import importlib.abc
import importlib.util
import sys
from pathlib import Path


class SchedulerOverlay(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "vllm.v1.core.sched.scheduler":
            return importlib.util.spec_from_file_location(
                fullname, Path(__file__).with_name("observed_scheduler.py"))
        return None


sys.meta_path.insert(0, SchedulerOverlay())
'''

TRACE = '''
import json as _trace_json
import os as _trace_os

_trace_file = open(_trace_os.environ["LORA_TRACE_PATH"], "a", buffering=1, encoding="utf-8")
_trace_detailed = _trace_os.environ.get("LORA_TRACE_DETAIL", "full") == "full"
_trace_sample_every = int(_trace_os.environ.get("LORA_TRACE_SAMPLE_EVERY", "0"))


def _trace(event, request=None, **fields):
    row = {"event": event, "time_ns": time.monotonic_ns(), "pid": _trace_os.getpid(), **fields}
    if request is not None:
        row.update(request_id=request.request_id, status=request.status.name,
                   adapter=request.lora_request.lora_name if request.lora_request else None)
    _trace_file.write(_trace_json.dumps(row) + "\\n")


_trace("scheduler_loaded", source=__file__)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    pinned = json.loads((root / "env/g0-runtime.json").read_text())
    from importlib.util import find_spec
    spec = find_spec("vllm")
    source_path = Path(spec.origin).parent / "v1/core/sched/scheduler.py"
    source = source_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != pinned["installed_scheduler_sha256"]:
        raise SystemExit("Installed scheduler does not match the G0 manifest")
    source = source.decode()
    changes = {
        "\nclass Scheduler(SchedulerInterface):": TRACE + "\n\nclass Scheduler(SchedulerInterface):",
        "                    # Scheduling would exceed max_loras, skip.":
            '                    if _trace_detailed:\n'
            '                        _trace("skip_lora", request, active=sorted(scheduled_loras),\n'
            '                               limit=self.lora_config.max_loras,\n'
            '                               running=[r.request_id for r in self.running])\n'
            "                    # Scheduling would exceed max_loras, skip.",
        "                self.running.append(request)":
            '                self.running.append(request)\n'
            '                _trace("admit", request, active_before=sorted(scheduled_loras))',
        "            self.requests[request.request_id] = request":
            '            self.requests[request.request_id] = request\n'
            '            _trace("queued", request)',
        "        assert request.is_finished()\n\n        if self.aux_output_connector":
            '        assert request.is_finished()\n'
            '        _trace("finished", request)\n\n        if self.aux_output_connector',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise SystemExit(f"Expected one source match: {old!r}")
        source = source.replace(old, new)
    sys.path.insert(0, str(root / "patches"))
    from scheduler_integration import integrate
    source = integrate(source)
    compile(source, "observed_scheduler.py", "exec")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "observed_scheduler.py").write_text(source, encoding="utf-8")
    (args.output / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    shutil.copyfile(root / "patches/admission_policy.py", args.output / "admission_policy.py")


if __name__ == "__main__":
    main()
