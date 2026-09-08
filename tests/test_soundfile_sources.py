"""Integrity of notices and corresponding source for bundled SoundFile libraries."""

import hashlib
import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "stage_soundfile_sources", Path(__file__).parents[1] / "scripts/stage_soundfile_sources.py"
)
assert SPEC and SPEC.loader
source_stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source_stage)


def test_emulated_windows_python_cannot_select_host_arm_library(monkeypatch):
    import sysconfig

    monkeypatch.setattr(source_stage.platform, "system", lambda: "Windows")
    monkeypatch.setattr(source_stage.platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-amd64")
    with pytest.raises(source_stage.SourceError, match="interpreter architecture"):
        source_stage.native_target()


def test_modified_native_library_cannot_use_the_wrong_source_provenance(tmp_path):
    binary = tmp_path / "libsndfile.dylib"
    binary.write_bytes(b"abc")
    pin = {"bytes": 3, "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
    source_stage.verify_file(binary, pin)
    binary.write_bytes(b"abd")
    with pytest.raises(source_stage.SourceError, match="SHA-256"):
        source_stage.verify_file(binary, pin)


def test_license_member_must_be_a_regular_file(tmp_path):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as out:
        member = tarfile.TarInfo("source/COPYING")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        out.addfile(member)
    with pytest.raises(source_stage.SourceError, match="regular"):
        source_stage.license_bytes(archive, "source/COPYING")


def test_license_is_read_exactly_without_extracting_other_members(tmp_path):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as out:
        for name, data in [("source/COPYING", b"license\r\n"), ("../../escape", b"bad")]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            out.addfile(member, io.BytesIO(data))
    assert source_stage.license_bytes(archive, "source/COPYING") == b"license\r\n"
    assert not (tmp_path / "escape").exists()


def staged(directory):
    names = {"licenses/libsndfile/COPYING": b"license", "source/upstream/example.tar": b"source"}
    for name, data in names.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    value = {"schema_version": 1, "target": "macos-arm64", "soundfile_version": "0.14.0",
             "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                       for name, data in names.items()}}
    (directory / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    return value


def test_missing_or_changed_corresponding_source_fails_integrity(tmp_path):
    staged(tmp_path)
    source_stage.verify_stage(tmp_path)
    (tmp_path / "source/upstream/example.tar").write_bytes(b"change")
    with pytest.raises(source_stage.SourceError, match="SHA-256"):
        source_stage.verify_stage(tmp_path)


def test_source_manifest_never_follows_an_unrecorded_symlink(tmp_path):
    staged(tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "private.txt").write_bytes(b"private")
    (tmp_path / "source/external").symlink_to(outside, target_is_directory=True)
    with pytest.raises(source_stage.SourceError, match="symlink"):
        source_stage.verify_stage(tmp_path)


def test_source_manifest_rejects_paths_outside_stage(tmp_path):
    value = staged(tmp_path)
    value["files"]["../outside"] = {"bytes": 1, "sha256": "0" * 64}
    (tmp_path / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(source_stage.SourceError, match="path"):
        source_stage.verify_stage(tmp_path)


@pytest.mark.parametrize(
    ("port", "archive", "observed_identifier"),
    [
        ("mpg123", "mpg123-1.32.9.tar.bz2", "66150af195"),
        ("opus", "opus-vcpkg-1.5.2.tar.gz", "81ed242155"),
    ],
)
def test_windows_sources_and_ordered_patches_match_actual_dll_identifiers(
    port, archive, observed_identifier
):
    config = Path(__file__).parents[1] / "packaging/soundfile"
    pins = json.loads((config / "pins.json").read_text(encoding="utf-8"))
    source = next(pin for pin in pins["sources"] if pin["name"] == archive)
    recipe = config / "vcpkg-recipes/ports" / port
    portfile = (recipe / "portfile.cmake").read_text(encoding="utf-8")
    assert re.search(r"SHA512\s+([a-f0-9]+)", portfile)[1] == source["sha512"]
    patch_names = re.search(r"PATCHES\s+([^)]*)\)", portfile)[1].split()
    combined = source["sha512"] + "".join(
        hashlib.sha512((recipe / name).read_bytes()).hexdigest() for name in patch_names
    )
    assert hashlib.sha512(combined.encode("ascii")).hexdigest()[:10] == observed_identifier
