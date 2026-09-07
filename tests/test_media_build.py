"""Integrity boundaries for the independently distributed media executables."""

import hashlib
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_media_tools.py"
SPEC = importlib.util.spec_from_file_location("build_media_tools", SCRIPT)
assert SPEC and SPEC.loader
media_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media_build)


def archive_at(path, members):
    with tarfile.open(path, "w") as archive:
        for name, content, kind in members:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                member.type = kind
                member.linkname = content
                archive.addfile(member)
    return path


def test_changed_source_is_rejected_before_extraction(tmp_path):
    archive = tmp_path / "source.tar.xz"
    archive.write_bytes(b"abc")
    pin = {"sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "bytes": 3}
    media_build.verify_archive(archive, pin)
    archive.write_bytes(b"abd")
    with pytest.raises(media_build.BuildError, match="SHA-256"):
        media_build.verify_archive(archive, pin)


@pytest.mark.parametrize(
    "name,kind,link",
    [
        ("../escape", "file", b"bad"),
        ("ffmpeg-9.0.1/../../escape", "file", b"bad"),
        ("/absolute", "file", b"bad"),
        ("ffmpeg-9.0.1/..\\escape", "file", b"bad"),
        ("ffmpeg-9.0.1/link", tarfile.SYMTYPE, "../../escape"),
        ("ffmpeg-9.0.1/link", tarfile.LNKTYPE, "../../escape"),
        ("ffmpeg-9.0.1/device", tarfile.CHRTYPE, ""),
        ("other-root/file", "file", b"bad"),
    ],
)
def test_unsafe_source_members_never_write_partial_tree(tmp_path, name, kind, link):
    archive = archive_at(
        tmp_path / "input.tar",
        [
            ("ffmpeg-9.0.1/good", b"ok", "file"),
            (name, link, kind),
        ],
    )
    target = tmp_path / "unpacked"
    with pytest.raises(media_build.BuildError):
        media_build.safe_extract(archive, target, "ffmpeg-9.0.1")
    assert not target.exists()
    assert not (tmp_path / "escape").exists()


def test_duplicate_archive_paths_are_rejected(tmp_path):
    archive = archive_at(
        tmp_path / "input.tar",
        [
            ("ffmpeg-9.0.1/file", b"one", "file"),
            ("ffmpeg-9.0.1/file", b"two", "file"),
        ],
    )
    with pytest.raises(media_build.BuildError, match="duplicate"):
        media_build.safe_extract(archive, tmp_path / "unpacked", "ffmpeg-9.0.1")


def test_valid_source_extracts_executable_without_world_write_bits(tmp_path):
    archive = tmp_path / "input.tar"
    with tarfile.open(archive, "w") as out:
        member = tarfile.TarInfo("ffmpeg-9.0.1/configure")
        member.size, member.mode = 2, 0o7777
        out.addfile(member, io.BytesIO(b"ok"))
    target = tmp_path / "unpacked"
    result = media_build.safe_extract(archive, target, "ffmpeg-9.0.1")
    assert result == target / "ffmpeg-9.0.1"
    assert (result / "configure").read_bytes() == b"ok"
    if os.name == "posix":
        assert (result / "configure").stat().st_mode & 0o7777 == 0o755


def manifest_at(directory):
    files = {
        "bin/ffmpeg": b"first executable",
        "bin/ffprobe": b"second executable",
        "licenses/FFmpeg/COPYING.LGPLv2.1": b"license",
    }
    for name, data in files.items():
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    manifest = {
        "schema_version": 1,
        "target": "macos-arm64",
        "ffmpeg_version": "9.0.1",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files.items()
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_manifest_detects_changed_or_missing_payload(tmp_path):
    manifest_at(tmp_path)
    media_build.validate_manifest(tmp_path)
    (tmp_path / "bin/ffmpeg").write_bytes(b"other executable")
    with pytest.raises(media_build.BuildError, match="bin/ffmpeg"):
        media_build.validate_manifest(tmp_path)
    (tmp_path / "bin/ffmpeg").unlink()
    with pytest.raises(media_build.BuildError, match="bin/ffmpeg"):
        media_build.validate_manifest(tmp_path)


def test_manifest_rejects_unrecorded_executable(tmp_path):
    manifest_at(tmp_path)
    (tmp_path / "bin/unrecorded").write_bytes(b"hidden")
    with pytest.raises(media_build.BuildError, match="unrecorded"):
        media_build.validate_manifest(tmp_path)


def test_manifest_cannot_hash_paths_outside_bundle(tmp_path):
    manifest = manifest_at(tmp_path)
    manifest["files"]["../escape"] = {"sha256": "0" * 64, "bytes": 1}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(media_build.BuildError, match="path"):
        media_build.validate_manifest(tmp_path)


def test_manifest_rejects_symlink_even_with_matching_content(tmp_path):
    manifest_at(tmp_path)
    executable = tmp_path / "bin/ffmpeg"
    outside = tmp_path / "outside"
    outside.write_bytes(executable.read_bytes())
    executable.unlink()
    executable.symlink_to(outside)
    with pytest.raises(media_build.BuildError, match="symlink"):
        media_build.validate_manifest(tmp_path)


def test_manifest_rejects_unrecorded_symlink_directory(tmp_path):
    manifest_at(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")
    (tmp_path / "licenses/external").symlink_to(outside, target_is_directory=True)
    with pytest.raises(media_build.BuildError, match="symlink"):
        media_build.validate_manifest(tmp_path)


def test_manifest_requires_both_tools(tmp_path):
    manifest = manifest_at(tmp_path)
    del manifest["files"]["bin/ffprobe"]
    (tmp_path / "bin/ffprobe").unlink()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(media_build.BuildError, match="ffprobe"):
        media_build.validate_manifest(tmp_path)


def test_manifest_requires_the_actual_ffmpeg_license(tmp_path):
    manifest = manifest_at(tmp_path)
    license_path = "licenses/FFmpeg/COPYING.LGPLv2.1"
    del manifest["files"][license_path]
    (tmp_path / license_path).unlink()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(media_build.BuildError, match="license"):
        media_build.validate_manifest(tmp_path)


@pytest.mark.parametrize(
    "family,header",
    [
        ("macos", b"\xcf\xfa\xed\xfe"),
        ("linux", b"\x7fELF\x02\x01"),
        ("windows", b"MZ"),
    ],
)
def test_truncated_executables_fail_as_invalid_builds(tmp_path, family, header):
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(header)
    with pytest.raises(media_build.BuildError, match="architecture"):
        media_build.binary_architecture(executable, family, "arm64")


def test_wrong_architecture_is_rejected_without_executing_it(tmp_path):
    executable = tmp_path / "ffmpeg"
    # Little-endian 64-bit Mach-O header with the x86_64 CPU type.
    executable.write_bytes(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01" + bytes(56))
    media_build.binary_architecture(executable, "macos", "x64")
    with pytest.raises(media_build.BuildError, match="architecture"):
        media_build.binary_architecture(executable, "macos", "arm64")


def test_upstream_wrapped_license_output_is_accepted():
    media_build.check_license(
        "terms of the GNU Lesser General Public\nLicense as published by the "
        "Free Software Foundation; either\nversion 2.1 of the License"
    )


@pytest.mark.parametrize(
    "notice",
    [
        "GNU General Public License version 3",
        "GNU Lesser General Public License version 3",
        "nonfree and unredistributable",
    ],
)
def test_unexpected_effective_license_blocks_distribution(notice):
    with pytest.raises(media_build.BuildError, match="LGPL"):
        media_build.check_license(notice)


def test_macos_bundle_includes_its_static_compiler_runtime_notice(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "LICENSE.md").write_text("FFmpeg", encoding="utf-8")
    (source / "COPYING.LGPLv2.1").write_text("LGPL", encoding="utf-8")
    target = tmp_path / "licenses"
    media_build.copy_licenses(source, target, "macos", "arm64", tmp_path)
    assert "Apache License" in (target / "LLVM-compiler-rt-LICENSE.txt").read_text(encoding="utf-8")
