"""Resolve the candidate tag, snapshot scheduler, and record exact evidence."""
import argparse
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lora-admission-g0"})
    return urllib.request.urlopen(req, timeout=60).read()


def fetch(root, tag):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Expected a release tag such as v0.33.0")
    try:
        ref = json.loads(get(f"https://api.github.com/repos/vllm-project/vllm/git/ref/tags/{tag}"))
        obj = ref["object"]
        while obj["type"] == "tag":
            obj = json.loads(get(obj["url"]))["object"]
        if obj["type"] != "commit":
            raise ValueError("Tag does not resolve to a commit")
        commit = obj["sha"]
    except urllib.error.HTTPError as e:
        if e.code not in (403, 429):
            raise
        # Public API rate limits need no credentials: use Git's tag resolution.
        refs = subprocess.check_output(["git", "ls-remote", "https://github.com/vllm-project/vllm.git",
                                        f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], timeout=90, text=True)
        resolved = dict(line.split()[::-1] for line in refs.splitlines())
        commit = resolved.get(f"refs/tags/{tag}^{{}}", resolved.get(f"refs/tags/{tag}"))
        if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Cannot resolve upstream commit")
    source_path = "vllm/v1/core/sched/scheduler.py"
    url = f"https://raw.githubusercontent.com/vllm-project/vllm/{commit}/{source_path}"
    data = get(url)
    target = root / "vendor" / "vllm" / source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    lines = data.decode().splitlines()
    hits = [{"line": i, "text": line.strip()} for i, line in enumerate(lines, 1)
            if "max_loras" in line or "self.running.append(request)" in line]
    evidence = {"candidate_tag": tag, "commit": commit, "source_url": url,
                "scheduler_sha256": hashlib.sha256(data).hexdigest(), "locations": hits,
                "runtime_verified": False, "wheel": None, "model_revision": None}
    (root / "env").mkdir(exist_ok=True)
    (root / "env" / "upstream-source.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="v0.33.0")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args()
    fetch(args.root, args.tag)
