#!/usr/bin/env python3
"""Stage exact component notices for the pinned embedded CPython distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import sysconfig
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "3.12.13"
BUILD = "20260504"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def interpreter_identity(*, prefix: Path | None = None) -> dict:
    version = platform.python_version()
    if sys.implementation.name != "cpython" or version != VERSION:
        raise ValueError(f"Embedded Python must be CPython {VERSION}; found {version}")
    prefix = Path(sys.base_prefix) if prefix is None else prefix
    marker = prefix / "BUILD"
    if not marker.is_file():
        raise ValueError("Embedded Python is missing its managed BUILD identity")
    build = marker.read_text(encoding="utf-8").strip()
    if build != BUILD:
        raise ValueError(f"Embedded Python build must be {BUILD}; found {build}")
    machine = platform.machine().lower()
    arch = {"aarch64": "aarch64", "arm64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}.get(
        machine
    )
    family = {
        "darwin": "apple-darwin",
        "win32": "pc-windows-msvc",
        "linux": "unknown-linux-gnu",
    }.get(sys.platform)
    if arch is None or family is None:
        raise ValueError(f"Unsupported embedded Python target: {sys.platform}/{machine}")
    if sys.platform == "win32":
        interpreter_arch = {"win-amd64": "x86_64", "win-arm64": "aarch64"}.get(
            sysconfig.get_platform().lower()
        )
        if interpreter_arch != arch:
            raise ValueError(
                f"Embedded interpreter architecture {interpreter_arch} does not match "
                f"the native Windows host {arch}"
            )
    requested_arch = os.environ.get("CLEANTAKE_NATIVE_ARCH")
    if requested_arch and {"x64": "x86_64", "arm64": "aarch64"}.get(requested_arch) != arch:
        raise ValueError(
            f"Embedded Python does not match requested native architecture {requested_arch}"
        )
    if sys.platform == "linux" and platform.libc_ver()[0] != "glibc":
        raise ValueError("The pinned Linux interpreter requires the glibc distribution")
    return {"python_version": version, "build": build, "target": f"{arch}-{family}"}


def pins() -> dict:
    result = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    if result["python_version"] != VERSION or result["build"] != BUILD:
        raise ValueError("Notice manifest does not match the pinned Python build")
    return result


def checked_files(directory: Path, files: dict) -> None:
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Notice payload contains a symbolic link: {path.name}")
        if path.is_file() and path != directory / "manifest.json":
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(files):
        raise ValueError(f"Missing or unrecorded notice files: {sorted(actual ^ set(files))}")
    for name, info in files.items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Notice path escapes its payload directory")
        if path.stat().st_size != info["size"] or sha256(path) != info["sha256"]:
            raise ValueError(f"Notice hash or size does not match: {name}")


def stage_notices(output: Path) -> dict:
    identity = interpreter_identity()
    locked = pins()
    record = locked["targets"][identity["target"]]
    source = HERE / "targets" / identity["target"]
    checked_files(source, record["files"])
    if output.exists() or output.is_symlink():
        raise ValueError("Notice output already exists; choose a new directory")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, **identity, **record}
    with tempfile.TemporaryDirectory(prefix=".python-notices-", dir=output.parent) as temporary:
        staged = Path(temporary) / "payload"
        shutil.copytree(source, staged)
        (staged / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        verify_staged(staged)
        os.rename(staged, output)
    return manifest


def verify_staged(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    record = pins()["targets"].get(manifest.get("target"))
    if record is None:
        raise ValueError("Notice payload has an unknown Python target")
    expected = {
        "schema_version": 1,
        "python_version": VERSION,
        "build": BUILD,
        "target": manifest["target"],
        **record,
    }
    if manifest != expected:
        raise ValueError("Notice manifest does not match the pinned provenance")
    checked_files(directory, record["files"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_staged(args.output) if args.verify else stage_notices(args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Python component notices failed: {exc}\n")
    print(
        json.dumps(
            {"target": result["target"], "build": result["build"], "files": len(result["files"])}
        )
    )


if __name__ == "__main__":
    main()
