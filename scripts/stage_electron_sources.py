#!/usr/bin/env python3
"""Stage the pinned Electron covered sources and rebuild/replacement instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "packaging" / "electron"


class SourceError(RuntimeError):
    """The source supplement does not match its trusted release inputs."""


def file_pin(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": digest}


def verify_file(path: Path, pin: dict) -> None:
    if path.is_symlink() or not path.is_file():
        raise SourceError(f"Expected regular file: {path.name}")
    if file_pin(path) != {"bytes": pin["bytes"], "sha256": pin["sha256"]}:
        raise SourceError(f"Size/SHA-256 mismatch: {path.name}")


def safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or ":" in name
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise SourceError(f"Unsafe path: {name!r}")
    return path


def license_bytes(archive: Path, name: str) -> bytes:
    safe_path(name)
    with tarfile.open(archive, "r:*") as source:
        matches = [member for member in source if member.name == name]
        if len(matches) != 1 or not matches[0].isfile():
            raise SourceError(f"License must be one regular archive member: {name}")
        if not 0 < matches[0].size <= 2 * 1024 * 1024:
            raise SourceError(f"License size is invalid: {name}")
        stream = source.extractfile(matches[0])
        if stream is None:
            raise SourceError(f"License cannot be read: {name}")
        with stream:
            return stream.read()


def load_pins() -> dict:
    value = json.loads((CONFIG / "pins.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise SourceError("Unsupported trusted source pins")
    lock = json.loads((ROOT / "desktop/package-lock.json").read_text(encoding="utf-8"))
    version = lock.get("packages", {}).get("node_modules/electron", {}).get("version")
    if version != value.get("electron_version"):
        raise SourceError("Locked Electron version differs from source pins")
    return value


def download(pin: dict, cache: Path) -> Path:
    safe_path(pin["name"])
    target = cache / pin["name"]
    if target.exists() or target.is_symlink():
        verify_file(target, pin)
        return target
    if not pin["url"].startswith("https://"):
        raise SourceError("Source URL must use HTTPS")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as out:
            temporary = Path(out.name)
            request = urllib.request.Request(
                pin["url"], headers={"User-Agent": "CleanTake-source-stage"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise SourceError("Source redirected away from HTTPS")
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > pin["bytes"]:
                        raise SourceError("Source download exceeds pinned size")
                    out.write(block)
        verify_file(temporary, pin)
        temporary.replace(target)
        return target
    except (OSError, urllib.error.URLError) as error:
        raise SourceError(f"Cannot acquire {pin['name']}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def expected_files(pins: dict) -> dict:
    expected = {"source/pins.json": file_pin(CONFIG / "pins.json")}

    def add(name: str, pin: dict) -> None:
        safe_path(name)
        if name in expected:
            raise SourceError(f"Duplicate pinned destination: {name}")
        expected[name] = {"bytes": pin["bytes"], "sha256": pin["sha256"]}

    for source in pins["sources"]:
        safe_path(source["name"])
        add(f"source/upstream/{source['name']}", source)
        for notice in source.get("licenses", []):
            safe_path(notice["member"])
            add(f"licenses/{notice['destination']}", notice)
    for name, pin in pins["recipe_files"].items():
        add(f"source/recipes/{name}", pin)
    return expected


def metadata(pins: dict) -> dict:
    return {"schema_version": 1, "target": "common", **{
        key: pins[key] for key in (
            "electron_version", "electron_revision", "chromium_version", "chromium_revision",
            "native_distributions",
        )
    }}


def validate_manifest(directory: Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise SourceError("Stage must not be a symlink")
    pins = load_pins()
    value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected = expected_files(pins)
    for key, item in metadata(pins).items():
        if value.get(key) != item:
            raise SourceError(f"Manifest {key} differs from trusted pins")
    if value.get("files") != expected:
        raise SourceError("Manifest inventory differs from trusted pinned sources")
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise SourceError(f"Stage contains a symlink: {path.name}")
        if path.is_file() and path != directory / "manifest.json":
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(expected):
        raise SourceError("Source manifest file inventory differs from staged files")
    for name, pin in expected.items():
        verify_file(directory / name, pin)
    return value


def stage(output: Path, cache: Path) -> dict:
    output, cache = Path(output), Path(cache)
    pins = load_pins()
    expected = expected_files(pins)
    if output.exists() or output.is_symlink():
        raise SourceError("Output already exists; use --verify to audit an existing stage")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="electron-source-stage-", dir=output.parent) as temp:
        directory = Path(temp) / "payload"
        upstream = directory / "source/upstream"
        upstream.mkdir(parents=True)
        for source in pins["sources"]:
            archive = download(source, cache)
            shutil.copyfile(archive, upstream / source["name"])
            for notice in source.get("licenses", []):
                destination = directory / "licenses" / safe_path(notice["destination"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(license_bytes(archive, notice["member"]))
                verify_file(destination, notice)
        for name, pin in pins["recipe_files"].items():
            source = CONFIG / safe_path(name)
            verify_file(source, pin)
            destination = directory / "source/recipes" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        shutil.copyfile(CONFIG / "pins.json", directory / "source/pins.json")
        value = {**metadata(pins), "files": expected}
        (directory / "manifest.json").write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        validate_manifest(directory)
        directory.rename(output)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".local/electron-source-cache")
    args = parser.parse_args()
    try:
        result = (validate_manifest(args.verify) if args.verify is not None
                  else stage(args.output, args.cache_dir))
    except (SourceError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f"Electron source verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"electron_version": result["electron_version"],
                      "target": result["target"], "verified_files": len(result["files"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
