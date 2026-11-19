"""Download an immutable model snapshot into the project's WSL workspace."""
import argparse
import json
from pathlib import Path


def main():
    from huggingface_hub import HfApi, snapshot_download
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen3-0.6B")
    p.add_argument("--revision", default="c1899de289a04d12100db370d81485cdf75e47ca")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    info = HfApi().model_info(args.model, revision=args.revision)
    path = snapshot_download(args.model, revision=info.sha, local_dir=args.output,
                             allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja"])
    manifest = {"model": args.model, "revision": info.sha, "path": str(Path(path).resolve())}
    (args.output / "download-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
