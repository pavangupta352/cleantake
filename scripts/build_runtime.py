#!/usr/bin/env python3
"""Freeze the locked application and an explicit standalone media-tool build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from build_media_tools import BuildError, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build(media: Path, output: Path) -> Path:
    media, output = media.resolve(), output.resolve()
    suffix = ".exe" if sys.platform == "win32" else ""
    target = output / "cleantake-runtime"
    if target.exists() or target.is_symlink():
        raise ValueError("Runtime output already exists; choose a new output directory")
    for name in ("ffmpeg", "ffprobe"):
        binary = media / "bin" / (name + suffix)
        if not binary.is_file() or binary.stat().st_size == 0:
            raise ValueError(f"Media directory is missing bin/{name}{suffix}")
    if not (media / "licenses").is_dir() or not (media / "manifest.json").is_file():
        raise ValueError("Media directory must include licenses/ and manifest.json")
    media_manifest = validate_manifest(media)
    family = {"darwin": "macos", "win32": "windows", "linux": "linux"}[sys.platform]
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}[
        platform.machine().lower()
    ]
    if media_manifest["target"] != f"{family}-{architecture}":
        raise ValueError("Media tools must match the native build OS and architecture")
    if not (ROOT / "src/cleantake/static/index.html").is_file():
        raise ValueError("Build the studio before freezing the runtime")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".runtime-build-", dir=output) as work:
        work = Path(work)
        env = dict(os.environ, CLEANTAKE_MEDIA_DIR=str(media))
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "--distpath",
                str(work / "dist"),
                "--workpath",
                str(work / "work"),
                str(ROOT / "packaging/cleantake.spec"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        staged = work / "dist/cleantake-runtime"
        warnings = work / "work/cleantake/warn-cleantake.txt"
        if warnings.is_file():
            warning_text = warnings.read_text(encoding="utf-8").replace(str(ROOT), "<checkout>")
            warning_text = warning_text.replace(sys.base_prefix, "<embedded-python-build>")
            (output / "runtime-build-warnings.txt").write_text(warning_text, encoding="utf-8")
        # Editable-install provenance contains developer checkout paths; it is
        # neither a runtime requirement nor a redistribution notice.
        for provenance in staged.glob("_internal/*.dist-info/direct_url.json"):
            provenance.unlink()
        manifest = {
            "schema_version": 1,
            "cleantake_version": metadata.version("cleantake"),
            "python": platform.python_version(),
            "platform": sys.platform,
            "architecture": platform.machine(),
            "build_os": platform.platform(),
            "pyinstaller": metadata.version("pyinstaller"),
            "hooks_contrib": metadata.version("pyinstaller-hooks-contrib"),
            "media_manifest": media_manifest,
            "source_sha256": {
                str(p.relative_to(ROOT)): digest(p)
                for p in sorted(
                    [
                        ROOT / "uv.lock",
                        ROOT / "pyproject.toml",
                        ROOT / "packaging/cleantake.spec",
                        ROOT / "packaging/runtime_entry.py",
                        *ROOT.glob("src/cleantake/**/*.py"),
                    ]
                )
            },
            "files": {
                str(p.relative_to(staged)).replace(os.sep, "/"): {
                    "sha256": digest(p),
                    "size": p.stat().st_size,
                }
                for p in sorted(staged.rglob("*"))
                if p.is_file()
            },
        }
        (staged / "runtime-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.rename(staged, target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.media_dir, args.output)
    except (BuildError, ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Runtime build failed: {error}\n")
    print(result)


if __name__ == "__main__":
    main()
