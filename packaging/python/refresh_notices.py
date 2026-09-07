#!/usr/bin/env python3
"""Recreate the committed notice subset from verified official full archives.

Developer tool: requires the zstd command. Normal builds use stage_notices.py
and the committed, hash-checked subset without downloading these archives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def license_paths(metadata):
    paths = set()

    def visit(value):
        if isinstance(value, dict):
            for key, entry in value.items():
                if key in {"license_path", "license_paths"}:
                    paths.update([entry] if isinstance(entry, str) else entry)
                else:
                    visit(entry)
        elif isinstance(value, list):
            for entry in value:
                visit(entry)

    visit(metadata)
    for path in paths:
        parts = PurePosixPath(path)
        if parts.is_absolute() or ".." in parts.parts or not path.startswith("licenses/"):
            raise ValueError(f"Unexpected upstream license path: {path}")
    return paths


def extract_notices(archive: Path, target: str, record: dict, output: Path):
    if archive.stat().st_size != record["size"] or digest(archive) != record["sha256"]:
        raise ValueError(f"Full archive hash or size mismatch: {archive.name}")
    zstd = shutil.which("zstd")
    if zstd is None:
        raise ValueError("Install zstd to regenerate notices from full archives")
    output.mkdir(parents=True, exist_ok=False)
    metadata = None
    wanted = set()
    written = set()
    process = subprocess.Popen([zstd, "--decompress", "--stdout", archive], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as stream:
            for member in stream:
                name = member.name.removeprefix("python/")
                if name == "PYTHON.json":
                    if metadata is not None or not member.isfile() or member.size > 10_000_000:
                        raise ValueError("Unexpected upstream Python metadata entry")
                    content = stream.extractfile(member).read()
                    metadata = json.loads(content)
                    if (
                        metadata["python_version"] != "3.12.13"
                        or metadata["target_triple"] != target
                    ):
                        raise ValueError("Upstream metadata does not match the pinned target")
                    wanted = license_paths(metadata)
                    (output / name).write_bytes(content)
                    written.add(name)
                elif name.startswith("licenses/LICENSE.") and name.endswith(".txt"):
                    if len(PurePosixPath(name).parts) != 2:
                        raise ValueError("Unexpected nested upstream license path")
                    if name in written or not member.isfile() or member.size > 1_000_000:
                        raise ValueError(f"Unexpected upstream notice entry: {name}")
                    destination = output / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(stream.extractfile(member).read())
                    written.add(name)
        if process.wait(timeout=30) != 0:
            raise ValueError("Full archive decompression failed")
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    supplements = {}
    locked = json.loads((HERE / "archives.json").read_text(encoding="utf-8"))
    for name in sorted(wanted - written):
        extra = locked.get("supplements", {}).get(name)
        source = HERE / "supplements" / Path(name).name
        if extra is None or not source.is_file():
            raise ValueError(f"Missing declared upstream notice: {name}")
        if source.stat().st_size != extra["size"] or digest(source) != extra["sha256"]:
            raise ValueError(f"Supplemental notice hash mismatch: {name}")
        shutil.copyfile(source, output / name)
        written.add(name)
        supplements[name] = extra
    if metadata is None or not wanted.issubset(written):
        raise ValueError(
            f"Archive did not contain all declared notices: {sorted(wanted - written)}"
        )
    return {
        "source": record,
        "build_options": metadata["build_options"],
        "notice_selection": (
            "All original full-archive license files and all metadata license references"
        ),
        "supplements": supplements,
        "files": {
            name: {"sha256": digest(output / name), "size": (output / name).stat().st_size}
            for name in sorted(written)
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    locked = json.loads((HERE / "archives.json").read_text(encoding="utf-8"))
    manifest = {key: value for key, value in locked.items() if key != "targets"}
    manifest["targets"] = {}
    for target, record in locked["targets"].items():
        manifest["targets"][target] = extract_notices(
            args.archives / record["name"], target, record, args.output / "targets" / target
        )
        print(f"Verified {target}", flush=True)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
