"""Collect evidence without installing or changing system configuration."""
import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=45)
        def decode(b):
            return b.decode("utf-16-le" if b"\x00" in b else "utf-8", errors="replace")
        return {"command": argv, "returncode": p.returncode,
                "stdout": decode(p.stdout), "stderr": decode(p.stderr)}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"command": argv, "returncode": None, "error": str(e)}


def collect():
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": sys.version,
              "executable": sys.executable,
              "gpu": command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv"]),
              "packages": {}, "g0_passed": False}
    for name in ("torch", "vllm", "transformers", "safetensors", "peft"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None
    if platform.system() == "Windows":
        report["wsl"] = command(["wsl", "--list", "--verbose"])
        report["wsl_gpu"] = command(["wsl", "-d", "Ubuntu-24.04-NestQuant", "--", "nvidia-smi"])
    else:
        try:
            import torch
            a = torch.arange(16, device="cuda", dtype=torch.float32).reshape(4, 4)
            torch.cuda.synchronize()
            b = a.to(torch.bfloat16)
            bf16_ok = bool(torch.allclose((b @ b).float().cpu(), (b.cpu() @ b.cpu()).float()))
            report["torch_cuda"] = {"cuda_version": torch.version.cuda,
                                    "device": torch.cuda.get_device_name(),
                                    "bf16_matmul_ok": bf16_ok,
                                    "matmul_ok": bool(torch.allclose((a @ a).cpu(), a.cpu() @ a.cpu()))}
        except Exception as e:
            report["torch_cuda"] = {"error": str(e)}
    # GPU probe alone never certifies the streaming/adapter-binding G0 gate.
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collect(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
