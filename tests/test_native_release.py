"""Synthetic Actions-layout fixtures test assembly gates, never attest to a build."""

import hashlib
import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/assemble_native_release.py"
VERSION = "0.2.0"
COMMIT = "a" * 40
TARGETS = [(p, a) for p in ("mac", "win", "linux") for a in ("x64", "arm64")]
RUNTIME_GATES = (
    "runtime_file_integrity", "doctor_empty_PATH", "first_run_sample_and_auth",
    "spawned_analysis_edit_preview", "export_wav", "export_flac", "archive_round_trip",
    "wavpack_import", "active_FFmpeg_tree_cancellation", "EOF_active_worker_cleanup",
    "crashed_backend_stops_worker_media_and_reopens", "restart_preserves_deletion",
    "missing_bundled_tool_fails",
)
APP_GATES = (
    "packaged_first_launch_empty_PATH", "sample_and_real_audio_clock", "repair_undo_redo",
    "native_history_and_text_editing", "native_export_downloads", "external_navigation_denied",
    "single_instance_focus", "quit_cancels_worker_without_orphans", "restart_preserves_saved_work",
)


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def put(path, value):
    data = value if isinstance(value, bytes) else (json.dumps(value) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return pin(data)


@pytest.fixture
def assembler():
    assert SCRIPT.is_file(), "Native release assembler is not implemented"
    spec = importlib.util.spec_from_file_location("assemble_native_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_inputs(tmp_path, monkeypatch, assembler):
    """Tiny fake binaries/sources exercise the real format and checks, not native code."""
    inputs = tmp_path / "downloads"
    config = tmp_path / "checkout"
    ffpin = {"archive": "ffmpeg.tar.xz", **pin(b"synthetic FFmpeg source"),
             "key": "key.asc", "key_sha256": pin(b"key")["sha256"],
             "signature": "source.asc", "signature_sha256": pin(b"signature")["sha256"]}
    muslpin = {"archive": "musl.tar.gz", **pin(b"synthetic musl source")}
    ffpins = {"ffmpeg": ffpin, "musl": muslpin}
    sfsource = {"name": "sndfile.tar.gz", **pin(b"synthetic sndfile source"),
                "targets": ["macos", "windows", "linux"]}
    sfbin = {"name": "libsndfile", **pin(b"native library")}
    sfpins = {"sources": [sfsource], "soundfile_version": "0.14.0", "targets": {
        f"{family}-{arch}": {"binary": sfbin}
        for family in ("macos", "windows", "linux") for arch in ("x64", "arm64")}}
    for platform, arch in TARGETS:
        target = f"{platform}-{arch}"
        family = {"mac": "macos", "win": "windows", "linux": "linux"}[platform]
        native = f"{family}-{arch}"
        packages = inputs / f"native-packages-{target}"
        evidence = inputs / f"native-evidence-{target}"
        media = packages / "build/native/media"
        source = media / "source"
        files = {"upstream/ffmpeg.tar.xz": put(source / "upstream/ffmpeg.tar.xz",
                                             b"synthetic FFmpeg source"),
                 "upstream/key.asc": put(source / "upstream/key.asc", b"key"),
                 "upstream/source.asc": put(source / "upstream/source.asc", b"signature"),
                 "packaging/ffmpeg/sources.json": put(source / "packaging/ffmpeg/sources.json",
                                                       ffpins)}
        if platform == "linux":
            files["upstream/musl.tar.gz"] = put(source / "upstream/musl.tar.gz",
                                                 b"synthetic musl source")
        license_pin = put(media / "licenses/FFmpeg/COPYING.LGPLv2.1", b"synthetic notice")
        manifest = {"schema_version": 1, "target": native, "source": ffpin,
                    "source_signature": {"status": "verified"},
                    "files": {"licenses/FFmpeg/COPYING.LGPLv2.1": license_pin,
                              "bin/ffmpeg": pin(b"not uploaded"),
                              "bin/ffprobe": pin(b"not uploaded")}}
        if platform == "linux":
            manifest["musl_source"] = muslpin
        put(media / "manifest.json", manifest)
        put(evidence / "media/manifest.json", manifest)
        files["results/build-manifest.json"] = put(source / "results/build-manifest.json", manifest)
        put(source / "SOURCE-MANIFEST.json", {"schema_version": 1, "target": native,
                                              "files": files})
        sf = packages / "build/native/soundfile"
        sffiles = {"source/upstream/sndfile.tar.gz": put(sf / "source/upstream/sndfile.tar.gz",
                                                       b"synthetic sndfile source"),
                   "source/pins.json": put(sf / "source/pins.json", sfpins),
                   "licenses/COPYING": put(sf / "licenses/COPYING", b"synthetic notice")}
        sfmanifest = {"schema_version": 1, "target": native, "soundfile_version": "0.14.0",
                      "native_library": sfbin, "sources": [sfsource], "files": sffiles}
        put(sf / "manifest.json", sfmanifest)
        put(evidence / "soundfile/manifest.json", sfmanifest)
        osname = {"mac": "darwin", "win": "win32", "linux": "linux"}[platform]
        runtime_manifest = {"schema_version": 1, "cleantake_version": VERSION,
                            "platform": osname, "architecture": arch,
                            "media_manifest": manifest, "soundfile_component_manifest": sfmanifest,
                            "files": {}}
        rmhash = put(evidence / "runtime/cleantake-runtime/runtime-manifest.json", runtime_manifest)
        runtime = {"schema_version": 1, "commit": COMMIT, "version": VERSION,
                   "platform": osname, "architecture": arch, "status": "passed",
                   "runtime_manifest_sha256": rmhash["sha256"],
                   "checks": [{"name": name, "status": "passed"} for name in RUNTIME_GATES]}
        put(evidence / "evidence/runtime.json", runtime)
        app = {"schema_version": 1, "commit": COMMIT, "platform": osname,
               "architecture": arch, "status": "passed",
               "checks": [{"name": name, "status": "passed"} for name in APP_GATES]}
        app["checks"][0].update(version=VERSION, sandbox=True, packaged=True,
                                contextIsolation=True, nodeIntegration=False)
        put(evidence / "evidence/installed-app/desktop-smoke.json", app)
        suffix = {"mac": "dmg", "win": "exe", "linux": "deb"}[platform]
        artifact_arch = "amd64" if platform == "linux" and arch == "x64" else arch
        name = f"CleanTake-{VERSION}-{platform}-{artifact_arch}.{suffix}"
        installer = put(packages / "dist/native" / name, target.encode())
        install = {"commit": COMMIT, "success": True, "installer": {"name": name, **installer},
                   "dependency_audit": {"architecture": arch, "binary_count": 1},
                   "signature": {"status": "synthetic-unit-fixture"},
                   "checks": [{"name": "installed-desktop", "exit_code": 0},
                              {"name": "uninstall-retains-projects", "files": 24},
                              {"name": "reinstall-retains-projects", "files": 24}]}
        put(evidence / "evidence/install.json", install)
    put(config / "packaging/ffmpeg/sources.json", ffpins)
    put(config / "packaging/soundfile/pins.json", sfpins)
    monkeypatch.setattr(assembler, "ROOT", config)
    retained = tmp_path / "retained"
    assets = []
    for kind, name in [("wheel", f"cleantake-{VERSION}-py3-none-any.whl"),
                       ("sdist", f"cleantake-{VERSION}.tar.gz"), ("demo", "cleantake-demo.zip")]:
        asset_pin = put(retained / name, b"synthetic retained " + kind.encode())
        validation = put(retained / f"{kind}-validation.txt", b"Synthetic unit fixture only")
        assets.append({"path": name, "kind": kind, "version": VERSION, "status": "passed",
                       **asset_pin, "validation": {"path": f"{kind}-validation.txt", **validation}})
    retained_manifest = retained / "assets.json"
    put(retained_manifest, {"schema_version": 1, "assets": assets})
    electron = tmp_path / "electron"
    electron_files = {"source/component.tar.gz": put(electron / "source/component.tar.gz",
                                                    b"synthetic Electron source"),
                      "licenses/COPYING": put(electron / "licenses/COPYING", b"notice")}
    put(electron / "manifest.json", {"schema_version": 1, "target": "common",
                                     "electron_version": "44.2.0", "files": electron_files})

    def synthetic_component_validator(directory):
        # This boundary's real archive/revision validation has its own source-stage
        # tests; assembly fixtures must not download or pretend to build Electron.
        manifest = assembler.read_json(directory / "manifest.json")
        assembler.inventory(directory, manifest["files"], exclude=("manifest.json",))
        return manifest

    monkeypatch.setattr(assembler, "validate_electron_sources", synthetic_component_validator)
    return inputs, tmp_path / "release", retained_manifest


def assemble(assembler, paths, **kwargs):
    inputs, output, retained = paths
    return assembler.assemble(inputs, output, VERSION, COMMIT, retained,
                              electron_source=inputs.parent / "electron", **kwargs)


def test_success_preserves_all_targets_sources_and_explicit_retained_assets(
    assembler, release_inputs
):
    result = assemble(assembler, release_inputs)
    output = release_inputs[1]
    assert len(result["platforms"]) == 6
    assert len(result["retained_assets"]) == 3
    with tarfile.open(output / f"CleanTake-{VERSION}-native-sources.tar.xz") as source:
        names = source.getnames()
        assert sum(name.endswith("upstream/ffmpeg.tar.xz") for name in names) == 6
        assert sum(name.endswith("upstream/sndfile.tar.gz") for name in names) == 6
        assert sum(name.endswith("upstream/musl.tar.gz") for name in names) == 2
        assert any(name.endswith("electron/source/component.tar.gz") for name in names)
    lines = (output / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == len(list(output.iterdir())) - 1
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("change", ["tamper", "mixed_commit", "missing_source", "missing_gate",
                                    "duplicate_gate", "wrong_version", "missing_target"])
def test_invalid_inputs_never_publish_partial_release(assembler, release_inputs, change):
    inputs, output, _ = release_inputs
    package = inputs / "native-packages-mac-arm64"
    evidence = inputs / "native-evidence-mac-arm64/evidence"
    if change == "tamper":
        (package / f"dist/native/CleanTake-{VERSION}-mac-arm64.dmg").write_bytes(b"tampered")
    elif change == "missing_source":
        (package / "build/native/media/source/upstream/ffmpeg.tar.xz").unlink()
    elif change == "missing_target":
        (inputs / "native-evidence-mac-arm64").rename(inputs / "missing-target")
    else:
        path = evidence / "runtime.json"
        value = json.loads(path.read_text())
        if change == "mixed_commit":
            value["commit"] = "b" * 40
        elif change == "wrong_version":
            value["version"] = "0.1.0"
        elif change == "missing_gate":
            value["checks"].pop()
        else:
            value["checks"].append(value["checks"][0])
        put(path, value)
    with pytest.raises(assembler.ReleaseError):
        assemble(assembler, release_inputs)
    assert not output.exists()


def test_unverified_linux_portable_is_excluded(assembler, release_inputs):
    inputs, output, _ = release_inputs
    name = f"CleanTake-{VERSION}-linux-arm64.tar.xz"
    put(inputs / "native-packages-linux-arm64/dist/native" / name, b"unverified portable")
    result = assemble(assembler, release_inputs)
    assert not (output / name).exists()
    assert any(item["name"] == name for item in result["excluded_assets"])


def test_requested_portable_requires_its_own_hash_and_smoke(assembler, release_inputs):
    with pytest.raises(assembler.ReleaseError):
        assemble(assembler, release_inputs, include_portable=True)


def test_symlink_in_sources_is_rejected(assembler, release_inputs, tmp_path):
    inputs, output, _ = release_inputs
    target = inputs / "native-packages-mac-arm64/build/native/media/source/escape"
    target.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(assembler.ReleaseError, match="symlink"):
        assemble(assembler, release_inputs)
    assert not output.exists()


def test_output_must_be_new(assembler, release_inputs):
    release_inputs[1].mkdir()
    put(release_inputs[1] / "keep.txt", b"existing work")
    with pytest.raises(assembler.ReleaseError):
        assemble(assembler, release_inputs)
    assert (release_inputs[1] / "keep.txt").read_bytes() == b"existing work"


def test_retained_validation_cannot_follow_a_directory_symlink(assembler, release_inputs, tmp_path):
    manifest = release_inputs[2]
    value = json.loads(manifest.read_text())
    outside = tmp_path / "outside"
    outside.mkdir()
    proof = value["assets"][0]["validation"]
    (manifest.parent / proof["path"]).rename(outside / "proof.txt")
    (manifest.parent / "linked").symlink_to(outside, target_is_directory=True)
    proof["path"] = "linked/proof.txt"
    put(manifest, value)
    with pytest.raises(assembler.ReleaseError, match="symlink"):
        assemble(assembler, release_inputs)


def test_manifest_platform_cannot_disagree_with_runtime_report(assembler, release_inputs):
    root = release_inputs[0] / "native-evidence-mac-arm64"
    path = root / "runtime/cleantake-runtime/runtime-manifest.json"
    value = json.loads(path.read_text())
    value["architecture"] = "x64"
    digest = put(path, value)
    runtime_path = root / "evidence/runtime.json"
    runtime = json.loads(runtime_path.read_text())
    runtime["runtime_manifest_sha256"] = digest["sha256"]
    put(runtime_path, runtime)
    with pytest.raises(assembler.ReleaseError, match="manifest"):
        assemble(assembler, release_inputs)


def test_duplicate_json_fields_are_not_accepted(assembler, tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"status":"failed","status":"passed"}')
    with pytest.raises(assembler.ReleaseError, match="Duplicate"):
        assembler.read_json(path)


def test_modified_retained_asset_cannot_reuse_prior_validation(assembler, release_inputs):
    manifest = release_inputs[2]
    value = json.loads(manifest.read_text())
    (manifest.parent / value["assets"][0]["path"]).write_bytes(b"a different wheel")
    with pytest.raises(assembler.ReleaseError, match="SHA-256"):
        assemble(assembler, release_inputs)
    assert not release_inputs[1].exists()


def test_source_inventory_cannot_name_a_parent_path(assembler, release_inputs):
    path = (release_inputs[0] / "native-packages-mac-arm64/build/native/media/source"
            / "SOURCE-MANIFEST.json")
    value = json.loads(path.read_text())
    value["files"]["../private"] = pin(b"private")
    put(path, value)
    with pytest.raises(assembler.ReleaseError, match="Unsafe path"):
        assemble(assembler, release_inputs)


def test_extra_installer_is_not_silently_published(assembler, release_inputs):
    folder = release_inputs[0] / "native-packages-mac-arm64/dist/native"
    put(folder / "CleanTake-0.1.0-mac-arm64.dmg", b"old release")
    with pytest.raises(assembler.ReleaseError, match="Unexpected"):
        assemble(assembler, release_inputs)


def test_only_explicitly_requested_and_verified_portables_are_published(assembler, release_inputs):
    inputs, output, _ = release_inputs
    for arch in ("x64", "arm64"):
        packages = inputs / f"native-packages-linux-{arch}"
        evidence = inputs / f"native-evidence-linux-{arch}/evidence"
        name = f"CleanTake-{VERSION}-linux-{arch}.tar.xz"
        archive_pin = put(packages / "dist/native" / name, b"synthetic portable")
        install = json.loads((evidence / "install.json").read_text())
        install["portable"] = {"name": name, **archive_pin}
        install["checks"].append({"name": "portable-desktop", "exit_code": 0})
        put(evidence / "install.json", install)
        app = json.loads((evidence / "installed-app/desktop-smoke.json").read_text())
        put(evidence / "portable-app/desktop-smoke.json", app)
    result = assemble(assembler, release_inputs, include_portable=True)
    assert not result["excluded_assets"]
    assert (output / f"CleanTake-{VERSION}-linux-x64.tar.xz").exists()
    assert (output / f"CleanTake-{VERSION}-linux-arm64.tar.xz").exists()


def test_release_requires_electron_corresponding_source(assembler, release_inputs):
    inputs, output, retained = release_inputs
    with pytest.raises(assembler.ReleaseError, match="Electron"):
        assembler.assemble(inputs, output, VERSION, COMMIT, retained, electron_source=None)
    assert not output.exists()


def test_source_modified_while_installers_are_copied_rejects_the_release(
    assembler, release_inputs, monkeypatch
):
    original_copy = assembler.shutil.copyfile
    source = (release_inputs[0] / "native-packages-mac-arm64/build/native/media/source"
              / "upstream/ffmpeg.tar.xz")

    def copy_with_external_source_change(src, dst):
        result = original_copy(src, dst)
        source.write_bytes(b"changed during installer copying")
        return result

    monkeypatch.setattr(assembler.shutil, "copyfile", copy_with_external_source_change)
    with pytest.raises(assembler.ReleaseError, match="Source changed"):
        assemble(assembler, release_inputs)
    assert not release_inputs[1].exists()


@pytest.mark.parametrize("changed", ["media", "electron", "runtime_evidence", "prior_validation"])
def test_previously_validated_bytes_cannot_be_recaptured_after_other_checks(
    assembler, release_inputs, monkeypatch, changed
):
    inputs, output, retained = release_inputs
    paths = {
        "media": inputs / "native-packages-mac-arm64/build/native/media/source"
                 / "upstream/ffmpeg.tar.xz",
        "electron": inputs.parent / "electron/source/component.tar.gz",
        "runtime_evidence": inputs / "native-evidence-mac-arm64/evidence/runtime.json",
        "prior_validation": retained.parent / "wheel-validation.txt",
    }
    original_verify = assembler.verify_retained

    def mutate_after_other_validation(path, version):
        result = original_verify(path, version)
        paths[changed].write_bytes(b"changed after validation before archive hash capture")
        return result

    monkeypatch.setattr(assembler, "verify_retained", mutate_after_other_validation)
    with pytest.raises(assembler.ReleaseError, match="Source changed"):
        assemble(assembler, release_inputs)
    assert not output.exists()
