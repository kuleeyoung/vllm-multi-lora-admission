"""Preserve source, teaching notes and raw results together with SHA256 checks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


INCLUDED = ("bench", "configs", "docs", "env", "patches", "scripts", "tests", "vendor", "results")


def collect(root):
    files = [root / name for name in (".gitignore", "README.md", "pyproject.toml")]
    for dirname in INCLUDED:
        for path in (root / dirname).rglob("*"):
            parts = path.relative_to(root).parts
            if path.is_file() and "__pycache__" not in parts and parts[:2] != ("results", "archive"):
                files.append(path)
    return sorted(files)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strip_scheduler_paths(data):
    lines = []
    for line in data.splitlines(keepends=True):
        event = json.loads(line)
        if event["event"] == "scheduler_loaded" and "source" in event:
            event["source"] = event["source"].replace("\\", "/").rsplit("/", 1)[-1]
            line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
        lines.append(line)
    return b"".join(lines)


def g3_audit_entries(root, *, strip_source_paths):
    # Support both the original script entry point and python -m.
    sys.path.insert(0, str(root))
    from bench.audit_g3 import SUITES, input_paths

    yield "README.md", (root / "docs/g3-audit-bundle.md").read_bytes()
    modules = {"bench.audit_g3", "bench.analyze_g1", "bench.analyze_competition"}
    for steps in SUITES.values():
        modules.update(module for module, _ in steps)
    for module in sorted(modules):
        path = Path(*module.split(".")).with_suffix(".py")
        yield path.as_posix(), (root / path).read_bytes()
    for suite, steps in SUITES.items():
        directory = Path("results/g3") / suite
        source = root / directory
        for path in input_paths(source, suite):
            data = (source / path).read_bytes()
            if path.name == "server.log":
                # The capacity analyzer only consumes these startup lines.
                data = b"".join(line for line in data.splitlines(keepends=True)
                                if b"Available KV cache memory:" in line or b"GPU KV cache size:" in line)
            if strip_source_paths and path.name == "events.jsonl":
                data = strip_scheduler_paths(data)
            yield (directory / path).as_posix(), data
        for _, names in steps:
            for name in names:
                yield (directory / name).as_posix(), (source / name).read_bytes()


def snapshot(root, output, *, g3_audit_only=False, strip_source_paths=False):
    if output.suffix != ".zip":
        raise ValueError("Expected a .zip output path")
    checksum = output.with_suffix(".zip.sha256")
    if output.exists() or checksum.exists():
        raise FileExistsError(f"A snapshot with this name already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = (g3_audit_entries(root, strip_source_paths=strip_source_paths) if g3_audit_only else
               ((path.relative_to(root).as_posix(), path.read_bytes()) for path in collect(root)))
    with TemporaryDirectory(prefix=".snapshot-", dir=output.parent) as staging:
        bundle = Path(staging) / output.name
        manifest = {}
        with ZipFile(bundle, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in entries:
                archive.writestr(name, data)
                manifest[name] = sha256(data)
            manifest_text = "".join(f"{digest}  {name}\n" for name, digest in manifest.items())
            archive.writestr("ARCHIVE-MANIFEST.sha256", manifest_text)
        with ZipFile(bundle) as archive:
            if archive.testzip() is not None or any(sha256(archive.read(name)) != digest
                                                    for name, digest in manifest.items()):
                raise ValueError("Archive integrity check failed")
            if g3_audit_only:
                extracted = Path(staging) / "extracted"
                archive.extractall(extracted)
                subprocess.run([sys.executable, "-E", "-S", "-m", "bench.audit_g3", "results/g3"],
                               cwd=extracted, check=True)
        digest = sha256(bundle.read_bytes())
        with output.open("xb") as file, bundle.open("rb") as source:
            shutil.copyfileobj(source, file)
        with checksum.open("x", encoding="ascii") as file:
            file.write(f"{digest}  {output.name}\n")
    print(f"{len(manifest)} verified files, {output.stat().st_size} bytes")
    print(digest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--g3-audit-only", action="store_true",
                        help="Package and verify the standalone CPU-only G3 audit")
    parser.add_argument("--strip-source-paths", action="store_true",
                        help="Keep only the scheduler filename in audit events")
    args = parser.parse_args()
    if args.strip_source_paths and not args.g3_audit_only:
        parser.error("--strip-source-paths requires --g3-audit-only")
    snapshot(Path(__file__).resolve().parents[1], args.output.resolve(),
             g3_audit_only=args.g3_audit_only, strip_source_paths=args.strip_source_paths)
