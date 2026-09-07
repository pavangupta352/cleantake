"""Behavioral checks for the native artifact verifier (no installer mutations)."""

import importlib.util
import io
import os
import platform
import shutil
import struct
import subprocess
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_ci", Path(__file__).resolve().parents[2] / "scripts/native_ci.py"
)
assert SPEC and SPEC.loader
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


def test_mount_verification_uses_filesystem_identity(tmp_path):
    owned = tmp_path / "Mounted café"
    owned.mkdir()
    alias = tmp_path / "Equivalent path"
    try:
        alias.symlink_to(owned, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows test account cannot create symlinks")
    ci.require_mountpoint([{"mount-point": str(alias)}], owned)
    other = tmp_path / "Not the installed image"
    other.mkdir()
    with pytest.raises(ValueError, match="owned test location"):
        ci.require_mountpoint([{"mount-point": str(other)}], owned)


@pytest.mark.parametrize("machine,expected", [(62, "x64"), (183, "arm64")])
def test_identifies_elf_target_and_rejects_truncation(machine, expected):
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, machine)
    assert ci.binary_architectures(bytes(header)) == {expected}
    with pytest.raises(ValueError, match="truncated"):
        ci.binary_architectures(bytes(header[:8]))


@pytest.mark.parametrize("machine,expected", [(0x8664, "x64"), (0xAA64, "arm64")])
def test_identifies_pe_target_from_offset_header(machine, expected):
    header = bytearray(256)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 128)
    header[128:132] = b"PE\0\0"
    struct.pack_into("<H", header, 132, machine)
    assert ci.binary_architectures(bytes(header)) == {expected}


def test_identifies_mach_universal_binary():
    header = b"\xca\xfe\xba\xbe" + struct.pack(
        ">IIIIIIIIIII", 2, 0x01000007, 3, 4096, 100, 12, 0x0100000C, 0, 8192, 100, 12
    )
    assert ci.binary_architectures(header) == {"x64", "arm64"}
    assert ci.binary_architectures(b"ordinary data") == set()


def test_dependency_boundary_rejects_external_runtime_and_checkout(tmp_path):
    system = platform.system()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    lib = bundle / "libpython3.12.so"
    lib.touch()
    assert ci.dependency_origin(lib, bundle, system) == "bundled"
    os_directory = (
        Path(os.environ["SystemRoot"]) / "System32" if system == "Windows" else Path("/usr/lib")
    )
    os_library = {"Windows": "kernel32.dll", "Darwin": "libSystem.B.dylib", "Linux": "libc.so.6"}[
        system
    ]
    assert ci.dependency_origin(os_directory / os_library, bundle, system) == "os"
    with pytest.raises(ValueError, match="runtime"):
        ci.dependency_origin(os_directory / "libpython3.12.so", bundle, system)
    with pytest.raises(ValueError, match="outside"):
        ci.dependency_origin(tmp_path / "checkout/libcustom.so", bundle, system)


def test_bundle_symlink_cannot_disguise_an_external_dependency(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outside = tmp_path / "outside.so"
    outside.touch()
    link = bundle / "looks-bundled.so"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows test account cannot create symlinks")
    with pytest.raises(ValueError, match="outside"):
        ci.dependency_origin(link, bundle, "Linux")


def test_retention_uses_file_content_including_hidden_project_data(tmp_path):
    (tmp_path / ".marker").write_text("retain", encoding="utf-8")
    project = tmp_path / "café project.json"
    project.write_text("accepted repair", encoding="utf-8")
    before = ci.workspace_hashes(tmp_path)
    ci.require_retained(tmp_path, before)
    project.write_text("changed project", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        ci.require_retained(tmp_path, before)
    project.unlink()
    with pytest.raises(ValueError, match="missing"):
        ci.require_retained(tmp_path, before)


def test_safe_archive_rejects_traversal_and_extracts_regular_files(tmp_path):
    archive = tmp_path / "portable.tar.xz"
    with tarfile.open(archive, "w:xz") as target:
        member = tarfile.TarInfo("CleanTake/café.txt")
        member.size = 5
        target.addfile(member, io.BytesIO(b"hello"))
    ci.extract_portable(archive, tmp_path / "valid")
    assert (tmp_path / "valid/CleanTake/café.txt").read_bytes() == b"hello"
    with tarfile.open(archive, "w:xz") as target:
        member = tarfile.TarInfo("../escaped")
        member.size = 5
        target.addfile(member, io.BytesIO(b"hello"))
    with pytest.raises((ValueError, tarfile.FilterError)):
        ci.extract_portable(archive, tmp_path / "invalid")
    assert not (tmp_path / "escaped").exists()


def test_diagnostic_redaction_preserves_errors_without_private_handshake():
    text = "failed http://127.0.0.1:1234/#token=abc_DEF-123 in request"
    assert ci.redact(text) == "failed http://127.0.0.1:1234/#token=[redacted] in request"


def test_artifact_selection_requires_exactly_one_matching_architecture(tmp_path):
    (tmp_path / "CleanTake-0.2.0-mac-arm64.dmg").touch()
    (tmp_path / "CleanTake-0.2.0-mac-x64.dmg").touch()
    assert ci.artifact(tmp_path, "arm64", ".dmg").name.endswith("arm64.dmg")
    (tmp_path / "CleanTake-0.3.0-mac-arm64.dmg").touch()
    with pytest.raises(ValueError, match="exactly one"):
        ci.artifact(tmp_path, "arm64", ".dmg")


@pytest.mark.skipif(platform.system() != "Darwin", reason="Exercises the real macOS loader")
def test_real_macos_binary_must_bundle_its_non_system_library(tmp_path):
    compiler = shutil.which("clang")
    assert compiler, "Xcode command tools are required on native macOS build hosts"
    source = tmp_path / "value.c"
    source.write_text("int value(void) { return 7; }\n", encoding="utf-8")
    main = tmp_path / "main.c"
    main.write_text("int value(void); int main(void) { return value() != 7; }\n", encoding="utf-8")
    bundle = tmp_path / "CleanTake café"
    bundle.mkdir()
    outside = tmp_path / "libvalue.dylib"
    subprocess.run(
        [compiler, "-dynamiclib", source, "-install_name", outside, "-o", outside], check=True
    )
    executable = bundle / "application (GPU)"
    subprocess.run([compiler, main, outside, "-o", executable], check=True)
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    with pytest.raises(ValueError, match="outside"):
        ci.audit(bundle, arch)
    bundled = bundle / "libvalue.dylib"
    subprocess.run(
        [
            compiler,
            "-dynamiclib",
            source,
            "-install_name",
            "@loader_path/libvalue.dylib",
            "-o",
            bundled,
        ],
        check=True,
    )
    subprocess.run([compiler, main, bundled, "-o", executable], check=True)
    outside.unlink()
    subprocess.run([executable], check=True, env={"PATH": ""})
    report = ci.audit(bundle, arch)
    assert report["binary_count"] == 2
    imports = [item for binary in report["binaries"] for item in binary["dependencies"]]
    assert any(item["origin"] == "bundled" for item in imports)


@pytest.mark.skipif(platform.system() != "Darwin", reason="Exercises the real macOS loader")
def test_macos_dylib_self_install_name_is_not_an_import(tmp_path):
    compiler = shutil.which("clang")
    assert compiler
    source = tmp_path / "value.c"
    source.write_text("int value(void) { return 7; }\n", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    subprocess.run(
        [
            compiler,
            "-dynamiclib",
            source,
            "-install_name",
            "@rpath/liboriginal.1.dylib",
            "-o",
            bundle / "librenamed_arm64.dylib",
        ],
        check=True,
    )
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    report = ci.audit(bundle, arch)
    assert report["binary_count"] == 1
    assert "@rpath/liboriginal.1.dylib" not in {
        item["name"] for item in report["binaries"][0]["dependencies"]
    }


def test_regular_and_delayed_windows_imports_are_both_audited():
    pe = bytearray(2048)
    pe[:2] = b"MZ"
    struct.pack_into("<I", pe, 60, 128)
    pe[128:132] = b"PE\0\0"
    struct.pack_into("<HH", pe, 132, 0x8664, 1)
    struct.pack_into("<H", pe, 148, 240)
    struct.pack_into("<H", pe, 152, 0x20B)
    struct.pack_into("<Q", pe, 176, 0x140000000)
    struct.pack_into("<II", pe, 152 + 112 + 8, 0x1000, 40)
    struct.pack_into("<II", pe, 152 + 112 + 13 * 8, 0x1040, 64)
    struct.pack_into("<IIII", pe, 392 + 8, 1024, 0x1000, 1024, 512)
    struct.pack_into("<I", pe, 512 + 12, 0x1100)
    struct.pack_into("<II", pe, 512 + 0x40, 1, 0x1140)
    pe[768:781] = b"KERNEL32.dll\0"
    pe[832:846] = b"python312.dll\0"
    assert ci.pe_imports(bytes(pe)) == {"KERNEL32.dll", "python312.dll"}
