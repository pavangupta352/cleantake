#!/usr/bin/env python3
"""Assemble verified Actions native artifacts and corresponding source; never publish."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [(p, a) for p in ("mac", "win", "linux") for a in ("x64", "arm64")]
RUNTIME_GATES = {
    "runtime_file_integrity", "doctor_empty_PATH", "first_run_sample_and_auth",
    "spawned_analysis_edit_preview", "export_wav", "export_flac", "archive_round_trip",
    "wavpack_import", "active_FFmpeg_tree_cancellation", "EOF_active_worker_cleanup",
    "crashed_backend_stops_worker_media_and_reopens", "restart_preserves_deletion",
    "missing_bundled_tool_fails",
}
APP_GATES = {
    "packaged_first_launch_empty_PATH", "sample_and_real_audio_clock", "repair_undo_redo",
    "native_history_and_text_editing", "native_export_downloads", "external_navigation_denied",
    "single_instance_focus", "quit_cancels_worker_without_orphans", "restart_preserves_saved_work",
}


class ReleaseError(RuntimeError):
    """An input is incomplete, inconsistent or fails a required release gate."""


def safe_path(name: str) -> PurePosixPath:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(ord(character) < 32 or ord(character) == 127 for character in name)
            or any(part in ("", ".", "..") for part in name.split("/"))
            or PurePosixPath(name).is_absolute()):
        raise ReleaseError(f"Unsafe path: {name!r}")
    return PurePosixPath(name)


def contained_file(root: Path, name: str) -> Path:
    path = root
    for part in safe_path(name).parts:
        path = path / part
        if path.is_symlink():
            raise ReleaseError(f"Retained path contains a symlink: {name}")
    return path


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ReleaseError(f"Missing regular JSON file: {path.name}")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ReleaseError(f"JSON file exceeds size limit: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError) as error:
        raise ReleaseError(f"Invalid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise ReleaseError(f"Expected JSON object: {path.name}")
    return value


def file_pin(path: Path) -> dict:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ReleaseError(f"Expected regular file: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": digest}


def verify_file(path: Path, pin: dict) -> dict:
    if not isinstance(pin, dict) or not re.fullmatch(r"[a-f0-9]{64}", pin.get("sha256", "")):
        raise ReleaseError(f"Invalid SHA-256 pin: {path.name}")
    if not path.is_file():
        raise ReleaseError(f"Missing source or artifact: {path.name}")
    actual = file_pin(path)
    if (actual["sha256"] != pin["sha256"]
            or ("bytes" in pin and actual["bytes"] != pin["bytes"])):
        raise ReleaseError(f"Size/SHA-256 mismatch: {path.name}")
    return actual


def tree(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ReleaseError(f"Missing directory or symlink: {root.name}")
    files = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        safe_path(name)
        if path.is_symlink():
            raise ReleaseError(f"Input contains a symlink: {name}")
        mode = path.stat().st_mode
        if stat.S_ISREG(mode):
            files[name] = path
        elif not stat.S_ISDIR(mode):
            raise ReleaseError(f"Input contains a special file: {name}")
    return files


def inventory(root: Path, pins: dict, *, exclude=()) -> dict[str, Path]:
    if not isinstance(pins, dict) or not pins:
        raise ReleaseError("Empty or invalid file inventory")
    for name in pins:
        safe_path(name)
    actual = tree(root)
    if set(actual) - set(exclude) != set(pins):
        raise ReleaseError(f"Source inventory mismatch: {root.name}")
    for name, pin in pins.items():
        verify_file(root / name, pin)
    return actual


def architecture(value: str) -> str:
    result = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64",
              "amd64": "x64", "x64": "x64"}.get(str(value).lower())
    if result is None:
        raise ReleaseError(f"Unknown architecture: {value!r}")
    return result


def checks(report: dict) -> dict[str, dict]:
    values = report.get("checks")
    if not isinstance(values, list):
        raise ReleaseError("Missing gate list")
    result = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise ReleaseError("Invalid gate record")
        if value["name"] in result:
            raise ReleaseError(f"Duplicate gate: {value['name']}")
        result[value["name"]] = value
    return result


def passed_report(path: Path, gates: set, commit: str, platform: str, arch: str) -> dict:
    report = read_json(path)
    expected_os = {"mac": "darwin", "win": "win32", "linux": "linux"}[platform]
    if report.get("schema_version") != 1:
        raise ReleaseError(f"Unsupported report schema: {path.name}")
    if report.get("commit") != commit:
        raise ReleaseError(f"Missing or mixed commit: {path.name}")
    if (report.get("platform") != expected_os
            or architecture(report.get("architecture")) != arch):
        raise ReleaseError(f"Mixed platform: {path.name}")
    observed = checks(report)
    if (report.get("status") != "passed" or not gates <= observed.keys()
            or any(value.get("status") != "passed" for value in observed.values())):
        raise ReleaseError(f"Required gates did not all pass: {path.name}")
    return report


def verify_app(path: Path, version: str, commit: str, platform: str, arch: str) -> dict:
    report = passed_report(path, APP_GATES, commit, platform, arch)
    launch = checks(report)["packaged_first_launch_empty_PATH"]
    if (launch.get("version") != version or launch.get("packaged") is not True
            or launch.get("sandbox") is not True or launch.get("contextIsolation") is not True
            or launch.get("nodeIntegration") is not False):
        raise ReleaseError("App version or packaged security gate differs from release")
    return report


def verify_media_sources(root: Path, target: str, trusted: dict) -> dict:
    manifest = read_json(root / "manifest.json")
    if manifest.get("target") != target or manifest.get("source") != trusted["ffmpeg"]:
        raise ReleaseError("Media source pins or target differ from release checkout")
    if manifest.get("source_signature", {}).get("status") != "verified":
        raise ReleaseError("Media source signature was not verified at build time")
    source = root / "source"
    source_manifest = read_json(source / "SOURCE-MANIFEST.json")
    if source_manifest.get("target") != target:
        raise ReleaseError("Media source inventory target mismatch")
    inventory(source, source_manifest.get("files"), exclude=("SOURCE-MANIFEST.json",))
    if read_json(source / "results/build-manifest.json") != manifest:
        raise ReleaseError("Media source build manifest differs from shipped manifest")
    if read_json(source / "packaging/ffmpeg/sources.json") != trusted:
        raise ReleaseError("Media rebuild pins differ from release checkout")
    ffmpeg = trusted["ffmpeg"]
    for key in ("archive", "key", "signature"):
        safe_path(ffmpeg[key])
        expected = ffmpeg if key == "archive" else {"sha256": ffmpeg[f"{key}_sha256"]}
        verify_file(source / "upstream" / ffmpeg[key], expected)
    if target.startswith("linux-"):
        musl = trusted["musl"]
        if manifest.get("musl_source") != musl:
            raise ReleaseError("Linux media is missing matching musl source pins")
        safe_path(musl["archive"])
        verify_file(source / "upstream" / musl["archive"], musl)
    license_pins = {name.removeprefix("licenses/"): pin
                    for name, pin in manifest.get("files", {}).items()
                    if name.startswith("licenses/")}
    if "FFmpeg/COPYING.LGPLv2.1" not in license_pins:
        raise ReleaseError("Missing FFmpeg LGPL notice")
    inventory(root / "licenses", license_pins)
    return manifest


def verify_soundfile_sources(root: Path, target: str, trusted: dict) -> dict:
    manifest = read_json(root / "manifest.json")
    sources = [pin for pin in trusted["sources"] if target.split("-")[0] in pin["targets"]]
    if (manifest.get("target") != target or manifest.get("sources") != sources
            or manifest.get("soundfile_version") != trusted["soundfile_version"]
            or manifest.get("native_library") != trusted["targets"][target]["binary"]):
        raise ReleaseError("SoundFile source or binary pins differ from release checkout")
    inventory(root, manifest.get("files"), exclude=("manifest.json",))
    if read_json(root / "source/pins.json") != trusted:
        raise ReleaseError("SoundFile rebuild pins differ from release checkout")
    if not sources or not any(name.startswith("licenses/") for name in manifest["files"]):
        raise ReleaseError("SoundFile source archives or notices are missing")
    for pin in sources:
        safe_path(pin["name"])
        verify_file(root / "source/upstream" / pin["name"], pin)
        for member in pin.get("license_members", []):
            safe_path(member)
            if f"licenses/{member}" not in manifest["files"]:
                raise ReleaseError(f"Missing SoundFile component notice: {member}")
    for name, pin in trusted.get("recipe_files", {}).items():
        safe_path(name)
        verify_file(root / "source/recipes" / name, pin)
    return manifest


def validate_electron_sources(directory: Path) -> dict:
    helper_path = Path(__file__).with_name("stage_electron_sources.py")
    if not helper_path.is_file():
        raise ReleaseError("Electron corresponding-source staging tool is missing")
    spec = importlib.util.spec_from_file_location("stage_electron_sources", helper_path)
    if spec is None or spec.loader is None:
        raise ReleaseError("Electron corresponding-source validator cannot be loaded")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    try:
        manifest = helper.validate_manifest(directory)
    except (helper.SourceError, OSError) as error:
        raise ReleaseError(f"Electron corresponding-source verification failed: {error}") from error
    locked_version = read_json(ROOT / "desktop/package-lock.json")["packages"][
        "node_modules/electron"]["version"]
    if (manifest.get("schema_version") != 1 or manifest.get("target") != "common"
            or manifest.get("electron_version") != locked_version):
        raise ReleaseError("Electron source version or schema differs from release checkout")
    inventory(directory, manifest.get("files"), exclude=("manifest.json",))
    return manifest


def artifact_name(version: str, platform: str, arch: str, *, portable=False) -> str:
    suffix = "tar.xz" if portable else {"mac": "dmg", "win": "exe", "linux": "deb"}[platform]
    spelling = "amd64" if suffix == "deb" and arch == "x64" else arch
    return f"CleanTake-{version}-{platform}-{spelling}.{suffix}"


def verify_target(inputs: Path, version: str, commit: str, platform: str, arch: str,
                  ffmpeg_pins: dict, soundfile_pins: dict, include_portable: bool) -> dict:
    target = f"{platform}-{arch}"
    family = {"mac": "macos", "win": "windows", "linux": "linux"}[platform]
    native = f"{family}-{arch}"
    packages = inputs / f"native-packages-{target}"
    evidence = inputs / f"native-evidence-{target}"
    package_files = tree(packages)
    tree(evidence)
    runtime_path = evidence / "evidence/runtime.json"
    runtime = passed_report(runtime_path, RUNTIME_GATES, commit, platform, arch)
    if runtime.get("version") != version:
        raise ReleaseError("Frozen runtime version differs from release")
    runtime_manifest_path = evidence / "runtime/cleantake-runtime/runtime-manifest.json"
    verify_file(runtime_manifest_path, {"sha256": runtime.get("runtime_manifest_sha256", "")})
    runtime_manifest = read_json(runtime_manifest_path)
    expected_os = {"mac": "darwin", "win": "win32", "linux": "linux"}[platform]
    if (runtime_manifest.get("schema_version") != 1
            or runtime_manifest.get("cleantake_version") != version
            or runtime_manifest.get("platform") != expected_os
            or architecture(runtime_manifest.get("architecture")) != arch):
        raise ReleaseError("Frozen runtime manifest version/platform differs from release")
    app_path = evidence / "evidence/installed-app/desktop-smoke.json"
    app = verify_app(app_path, version, commit, platform, arch)
    install_path = evidence / "evidence/install.json"
    install = read_json(install_path)
    if install.get("commit") != commit or install.get("success") is not True:
        raise ReleaseError("Installer evidence failed or belongs to another commit")
    install_checks = checks(install)
    if install_checks.get("installed-desktop", {}).get("exit_code") != 0:
        raise ReleaseError("Actual installed app did not pass")
    for name in ("uninstall-retains-projects", "reinstall-retains-projects"):
        if install_checks.get(name, {}).get("files", 0) < 2:
            raise ReleaseError(f"Missing successful retention gate: {name}")
    if architecture(install.get("dependency_audit", {}).get("architecture")) != arch:
        raise ReleaseError("Installed dependency audit architecture differs")
    installer_name = artifact_name(version, platform, arch)
    if install.get("installer", {}).get("name") != installer_name:
        raise ReleaseError("Installer filename/version differs from release")
    installer = packages / "dist/native" / installer_name
    installer_pin = verify_file(installer, install["installer"])
    artifacts = {installer_name: (installer, installer_pin)}
    excluded = []
    portable_name = artifact_name(version, platform, arch, portable=True)
    allowed_artifacts = {installer_name}
    evidence_paths = {"runtime.json": runtime_path, "runtime-manifest.json": runtime_manifest_path,
                      "installed-desktop.json": app_path, "install.json": install_path}
    if platform == "linux":
        portable = packages / "dist/native" / portable_name
        allowed_artifacts.add(portable_name)
        if include_portable:
            if (install.get("portable", {}).get("name") != portable_name
                    or install_checks.get("portable-desktop", {}).get("exit_code") != 0):
                raise ReleaseError("Portable archive has no successful hash-bound smoke")
            portable_pin = verify_file(portable, install["portable"])
            portable_app = evidence / "evidence/portable-app/desktop-smoke.json"
            verify_app(portable_app, version, commit, platform, arch)
            artifacts[portable_name] = (portable, portable_pin)
            evidence_paths["portable-desktop.json"] = portable_app
        elif portable.is_file():
            excluded.append({"name": portable_name, "reason": "Portable release not selected"})
    actual_artifacts = tree(packages / "dist/native")
    if set(actual_artifacts) - allowed_artifacts:
        raise ReleaseError("Unexpected, duplicate or mixed-version installer artifact")
    media_root = packages / "build/native/media"
    sf_root = packages / "build/native/soundfile"
    media = verify_media_sources(media_root, native, ffmpeg_pins)
    soundfile = verify_soundfile_sources(sf_root, native, soundfile_pins)
    for component, manifest in (("media", media), ("soundfile", soundfile)):
        if read_json(evidence / component / "manifest.json") != manifest:
            raise ReleaseError(f"Package and evidence {component} manifests differ")
    if (runtime_manifest.get("media_manifest") != media
            or runtime_manifest.get("soundfile_component_manifest") != soundfile):
        raise ReleaseError("Sources do not correspond to the tested frozen runtime")
    source_files = {}
    allowed_package_files = {f"dist/native/{name}" for name in actual_artifacts}
    for component, root in (("media", media_root), ("soundfile", sf_root)):
        for name, path in tree(root).items():
            if component == "media" and not (name == "manifest.json"
                                               or name.startswith(("source/", "licenses/"))):
                raise ReleaseError("Unexpected file in media source artifact")
            source_files[f"{target}/{component}/{name}"] = path
            allowed_package_files.add(path.relative_to(packages).as_posix())
    if set(package_files) != allowed_package_files:
        raise ReleaseError("Unexpected file outside package/source inventory")
    for name, path in evidence_paths.items():
        source_files[f"{target}/evidence/{name}"] = path
    return {
        "artifacts": artifacts, "source_files": source_files, "excluded": excluded,
        "summary": {"target": target, "commit": commit, "version": version,
                    "installer": {"name": installer_name, **installer_pin},
                    "frozen_gates": sorted(checks(runtime)), "app_gates": sorted(checks(app)),
                    "retention_gates": ["uninstall-retains-projects", "reinstall-retains-projects"],
                    "signature": {key: install.get("signature", {}).get(key)
                                  for key in ("status", "integrity_exit", "gatekeeper_exit")},
                    "runner": install.get("runner_image", {}),
                    "limits": install.get("limits", []),
                    "evidence": {name: file_pin(path) for name, path in evidence_paths.items()}},
    }


def verify_retained(path: Path, version: str) -> tuple[dict, dict, list]:
    declaration = read_json(path)
    if declaration.get("schema_version") != 1 or not isinstance(declaration.get("assets"), list):
        raise ReleaseError("Invalid retained-asset declaration")
    artifacts, evidence, summaries, kinds = {}, {}, [], set()
    expected_names = {"wheel": f"cleantake-{version}-py3-none-any.whl",
                      "sdist": f"cleantake-{version}.tar.gz", "demo": "cleantake-demo.zip"}
    for item in declaration["assets"]:
        kind = item.get("kind")
        if (kind not in expected_names or kind in kinds or item.get("version") != version
                or item.get("status") != "passed"):
            raise ReleaseError("Missing, duplicate or unverified retained asset")
        kinds.add(kind)
        relative = safe_path(item.get("path"))
        if relative.name != expected_names[kind]:
            raise ReleaseError("Retained asset filename/version mismatch")
        source = contained_file(path.parent, item["path"])
        actual = verify_file(source, item)
        validation = item.get("validation", {})
        validation_path = contained_file(path.parent, validation.get("path"))
        proof = verify_file(validation_path, validation)
        artifacts[source.name] = (source, actual)
        evidence[f"retained-evidence/{kind}-{validation_path.name}"] = validation_path
        summaries.append({"name": source.name, "kind": kind, "version": version, **actual,
                          "validation": proof,
                          "validation_origin": "Explicitly supplied prior validation; not rerun"})
    if kinds != set(expected_names):
        raise ReleaseError("Explicit wheel, sdist and demo validations are required")
    evidence["retained-evidence/declaration.json"] = path
    return artifacts, evidence, summaries


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def source_archive(destination: Path, files: dict[str, Path], prefix: str, records: dict) -> dict:
    for name, path in files.items():
        try:
            verify_file(path, records[name])
        except ReleaseError as error:
            raise ReleaseError(f"Source changed during assembly: {name}") from error
    index = json_bytes({"schema_version": 1, "files": records})
    with tarfile.open(destination, "w:xz", preset=6) as archive:
        for name, path in sorted(files.items()):
            safe_path(name)
            entry = tarfile.TarInfo(f"{prefix}/{name}")
            entry.size = records[name]["bytes"]
            entry.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            with path.open("rb") as stream:
                archive.addfile(entry, stream)
        entry = tarfile.TarInfo(f"{prefix}/SOURCE-INDEX.json")
        entry.mode, entry.size = 0o644, len(index)
        archive.addfile(entry, io.BytesIO(index))
    # Verify archived bytes, including a source changed between validation and copying.
    with tarfile.open(destination, "r:xz") as archive:
        for entry in archive:
            name = entry.name.removeprefix(prefix + "/")
            with archive.extractfile(entry) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            expected = (hashlib.sha256(index).hexdigest() if name == "SOURCE-INDEX.json"
                        else records[name]["sha256"])
            if digest != expected:
                raise ReleaseError(f"Source changed during assembly: {name}")
    return file_pin(destination)


def capture_source_records(input_files: dict[str, Path], retained: Path,
                           electron_source: Path) -> dict[Path, dict]:
    """Bind archive inputs before any source or evidence acceptance checks run."""
    paths = [path for name, path in input_files.items()
             if PurePosixPath(name).parts[1:3] != ("dist", "native")]
    paths.extend(tree(electron_source).values())
    paths.append(retained)
    declaration = read_json(retained)
    if not isinstance(declaration.get("assets"), list):
        raise ReleaseError("Invalid retained-asset declaration")
    for item in declaration["assets"]:
        if not isinstance(item, dict) or not isinstance(item.get("validation"), dict):
            raise ReleaseError("Missing retained validation record")
        paths.append(contained_file(retained.parent, item["validation"].get("path")))
    # Keep lexical absolute paths: resolving again after validation could follow
    # a newly substituted directory link and adopt another input's hash.
    return {path.absolute(): file_pin(path) for path in paths}


def assemble(inputs: Path, output: Path, version: str, commit: str, retained: Path,
             *, electron_source: Path | None = None, include_portable=False) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", version):
        raise ReleaseError("Expected an explicit safe release version")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ReleaseError("Expected the complete 40-character release commit")
    if output.exists() or output.is_symlink():
        raise ReleaseError("Output must be a new directory")
    if electron_source is None:
        raise ReleaseError("Exact Electron corresponding source is required")
    input_files = tree(inputs)
    expected = {f"native-{kind}-{platform}-{arch}"
                for platform, arch in TARGETS for kind in ("packages", "evidence")}
    if {path.name for path in inputs.iterdir()} != expected:
        raise ReleaseError("Expected exactly six package and six evidence artifact folders")
    initial_records = capture_source_records(input_files, retained, electron_source)
    electron_manifest = validate_electron_sources(electron_source)
    ffmpeg_pins = read_json(ROOT / "packaging/ffmpeg/sources.json")
    soundfile_pins = read_json(ROOT / "packaging/soundfile/pins.json")
    platforms, excluded, source_files, artifacts = [], [], {}, {}
    for platform, arch in TARGETS:
        result = verify_target(inputs, version, commit, platform, arch, ffmpeg_pins,
                               soundfile_pins, include_portable)
        if artifacts.keys() & result["artifacts"].keys():
            raise ReleaseError("Duplicate release artifact name")
        artifacts.update(result["artifacts"])
        source_files.update(result["source_files"])
        platforms.append(result["summary"])
        excluded.extend(result["excluded"])
    prior, prior_evidence, retained_summary = verify_retained(retained, version)
    if artifacts.keys() & prior.keys():
        raise ReleaseError("Duplicate retained artifact name")
    artifacts.update(prior)
    source_files.update(prior_evidence)
    source_files.update({f"electron/{name}": path
                         for name, path in tree(electron_source).items()})
    try:
        source_records = {name: initial_records[path.absolute()]
                          for name, path in source_files.items()}
    except KeyError as error:
        raise ReleaseError(
            "Source changed during validation: a new archive member appeared"
        ) from error
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-release-", dir=output.parent) as temporary:
        stage = Path(temporary) / "release"
        stage.mkdir()
        for name, (path, pin) in artifacts.items():
            shutil.copyfile(path, stage / name)
            verify_file(stage / name, pin)
        prefix = f"CleanTake-{version}-native-sources"
        source_pin = source_archive(
            stage / f"{prefix}.tar.xz", source_files, prefix, source_records
        )
        summary = {"schema_version": 1, "version": version, "commit": commit,
                   "platforms": platforms, "retained_assets": retained_summary,
                   "excluded_assets": excluded,
                   "electron_source": {"version": electron_manifest["electron_version"],
                                       "manifest": source_records["electron/manifest.json"]},
                   "corresponding_source": {"name": f"{prefix}.tar.xz", **source_pin},
                   "scope": "Offline assembly of supplied CI evidence and hash-verified assets. "
                            "No new build, smoke test, signature, attestation or publication."}
        (stage / "NATIVE-RELEASE.json").write_bytes(json_bytes(summary))
        sums = "".join(f"{file_pin(path)['sha256']}  {path.name}\n"
                       for path in sorted(stage.iterdir()))
        (stage / "SHA256SUMS").write_text(sums, encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise ReleaseError("Output appeared during assembly; refusing to replace it")
        stage.rename(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--electron-source", type=Path, required=True)
    parser.add_argument("--include-portable", action="store_true")
    args = parser.parse_args()
    try:
        summary = assemble(args.inputs, args.output, args.version, args.commit, args.retained,
                           electron_source=args.electron_source,
                           include_portable=args.include_portable)
        print(json.dumps({"version": summary["version"], "commit": summary["commit"],
                          "platforms": len(summary["platforms"]),
                          "excluded_assets": summary["excluded_assets"]}))
        return 0
    except (ReleaseError, OSError, KeyError, TypeError, ValueError, tarfile.TarError) as error:
        print(f"Native release assembly rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
