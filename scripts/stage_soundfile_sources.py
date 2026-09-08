#!/usr/bin/env python3
"""Verify the bundled SoundFile library and stage its notices and matching source."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import sysconfig
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "packaging" / "soundfile"


class SourceError(RuntimeError):
    """Source or native-library provenance failed validation."""


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


def native_target() -> str:
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    arch = {"aarch64": "arm64", "arm64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(
        platform.machine().lower()
    )
    if system is None or arch is None:
        raise SourceError("No pinned SoundFile wheel for this native target")
    if system == "windows":
        interpreter_arch = {"win-amd64": "x64", "win-arm64": "arm64"}.get(
            sysconfig.get_platform().lower()
        )
        if interpreter_arch != arch:
            raise SourceError(
                f"Python interpreter architecture {interpreter_arch} does not match "
                f"the native Windows host {arch}; select the native managed interpreter"
            )
    return f"{system}-{arch}"


def verify_installed(pins: dict, target: str) -> dict:
    import _soundfile_data
    import soundfile

    expected = pins["targets"][target]["binary"]
    if soundfile.__version__ != pins["soundfile_version"]:
        raise SourceError("Installed SoundFile version differs from source pins")
    if soundfile.__libsndfile_version__ != pins["libsndfile_version"]:
        raise SourceError("Loaded libsndfile version differs from source pins")
    binary = Path(_soundfile_data.__file__).parent / expected["name"]
    verify_file(binary, expected)
    # A fallback system library must never inherit the packaged wheel's provenance.
    if getattr(soundfile, "_full_path", None) != str(binary) or hasattr(soundfile, "_libname"):
        raise SourceError("SoundFile did not load the pinned packaged library")
    return expected


def download(pin: dict, cache: Path) -> Path:
    safe_path(pin["name"])
    target = cache / pin["name"]
    if target.exists() or target.is_symlink():
        verify_file(target, pin)
        return target
    cache.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in [pin["url"], *pin.get("mirrors", [])]:
        if not url.startswith("https://"):
            raise SourceError("Source URL must use HTTPS")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as out:
                temporary = Path(out.name)
                request = urllib.request.Request(
                    url, headers={"User-Agent": "CleanTake-source-stage"}
                )
                with urllib.request.urlopen(request, timeout=45) as response:
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
        except (OSError, urllib.error.URLError, SourceError) as error:
            errors.append(str(error))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise SourceError(f"Cannot acquire {pin['name']}: {'; '.join(errors)}")


def verify_stage(directory: Path) -> dict:
    if directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise SourceError("Stage must not be a symlink")
    value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("files"), dict):
        raise SourceError("Unsupported source manifest")
    for name in value["files"]:
        safe_path(name)
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise SourceError(f"Stage contains a symlink: {path.name}")
        if path.is_file() and path != directory / "manifest.json":
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(value["files"]):
        raise SourceError("Source manifest file inventory differs from staged files")
    for name, pin in value["files"].items():
        verify_file(directory / name, pin)
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stage(output: Path, cache: Path, pins: dict, target: str) -> dict:
    binary = verify_installed(pins, target)
    if output.exists() or output.is_symlink():
        raise SourceError("Output already exists; use --verify to audit an existing stage")
    output.parent.mkdir(parents=True, exist_ok=True)
    family = target.split("-")[0]
    sources = [pin for pin in pins["sources"] if family in pin["targets"]]
    with tempfile.TemporaryDirectory(prefix="soundfile-stage-", dir=output.parent) as temp:
        directory = Path(temp) / "payload"
        upstream = directory / "source" / "upstream"
        upstream.mkdir(parents=True)
        for pin in sources:
            archive = download(pin, cache)
            shutil.copyfile(archive, upstream / pin["name"])
            for member in pin["license_members"]:
                relative = safe_path(member)
                notice = directory / "licenses" / relative
                notice.parent.mkdir(parents=True, exist_ok=True)
                notice.write_bytes(license_bytes(archive, member))
        recipes = directory / "source" / "recipes"
        for name, pin in pins["recipe_files"].items():
            safe_path(name)
            source = CONFIG / name
            verify_file(source, pin)
            destination = recipes / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        shutil.copyfile(CONFIG / "pins.json", directory / "source" / "pins.json")
        shutil.copyfile(CONFIG / "README.md", directory / "source" / "README.md")
        shutil.copyfile(CONFIG / "NOTICE.md", directory / "licenses" / "NOTICE.md")
        shutil.copyfile(CONFIG / "upstream-license-notes.md",
                        directory / "licenses" / "upstream-license-notes.md")
        shutil.copyfile(Path(__file__), directory / "source" / "stage_soundfile_sources.py")
        value = {
            "schema_version": 1, "target": target,
            "soundfile_version": pins["soundfile_version"],
            "libsndfile_version": pins["libsndfile_version"], "native_library": binary,
            "wheel": pins["targets"][target]["wheel"],
            "components": pins["targets"][target]["components"],
            "provenance": {key: pins[key] for key in (
                "soundfile_commit", "binaries_commit", "windows_vcpkg_source_snapshot")},
            "sources": sources,
            "files": {path.relative_to(directory).as_posix(): file_pin(path)
                      for path in sorted(directory.rglob("*")) if path.is_file()},
        }
        write_json(directory / "manifest.json", value)
        verify_stage(directory)
        directory.rename(output)
    return value


def verify_current_stage(output: Path, pins: dict, target: str) -> dict:
    binary = verify_installed(pins, target)
    value = verify_stage(output)
    family = target.split("-")[0]
    sources = [pin for pin in pins["sources"] if family in pin["targets"]]
    if (value.get("target") != target or value.get("native_library") != binary
            or value.get("soundfile_version") != pins["soundfile_version"]
            or value.get("sources") != sources):
        raise SourceError("Existing stage does not match current native source pins")
    for pin in sources:
        verify_file(output / "source" / "upstream" / pin["name"], pin)
    for name, pin in pins["recipe_files"].items():
        verify_file(output / "source" / "recipes" / name, pin)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache-dir", type=Path, default=ROOT / "build" / "source-cache" / "soundfile"
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        pins = json.loads((CONFIG / "pins.json").read_text(encoding="utf-8"))
        target = native_target()
        value = (verify_current_stage(args.output, pins, target) if args.verify
                 else stage(args.output, args.cache_dir, pins, target))
        print(json.dumps({"target": target, "files": len(value["files"]),
                          "source_archives": len(value["sources"])}))
        return 0
    except (SourceError, OSError, ValueError, ImportError) as error:
        print(f"SoundFile source stage failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
