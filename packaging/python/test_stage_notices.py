"""Behavioral gates for exact embedded-Python notices."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "stage_notices", Path(__file__).with_name("stage_notices.py")
)
assert SPEC and SPEC.loader
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


def test_current_pinned_interpreter_stages_verified_component_notices(tmp_path):
    destination = tmp_path / "Python notices café"
    record = notices.stage_notices(destination)
    assert record["python_version"] == "3.12.13"
    assert record["build"] == "20260504"
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) > 5
    assert any("openssl" in name.lower() for name in manifest["files"])
    notices.verify_staged(destination)
    with pytest.raises(ValueError, match="exists"):
        notices.stage_notices(destination)


def test_notice_payload_modification_and_unrecorded_files_are_rejected(tmp_path):
    destination = tmp_path / "notices"
    notices.stage_notices(destination)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    first = destination / next(iter(manifest["files"]))
    original = first.read_bytes()
    first.write_bytes(original + b"changed")
    with pytest.raises(ValueError, match="hash|size"):
        notices.verify_staged(destination)
    first.write_bytes(original)
    (destination / "unrecorded.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="unrecorded"):
        notices.verify_staged(destination)


def test_different_python_build_cannot_reuse_pinned_notices(tmp_path):
    prefix = tmp_path / "python"
    prefix.mkdir()
    (prefix / "BUILD").write_text("20260901", encoding="utf-8")
    with pytest.raises(ValueError, match="build"):
        notices.interpreter_identity(prefix=prefix)


def test_missing_managed_build_identity_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="BUILD"):
        notices.interpreter_identity(prefix=tmp_path)


def test_emulated_windows_interpreter_cannot_claim_native_arm_notices(monkeypatch):
    import sysconfig

    monkeypatch.setattr(notices.sys, "platform", "win32")
    monkeypatch.setattr(notices.platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-amd64")
    with pytest.raises(ValueError, match="interpreter architecture"):
        notices.interpreter_identity()


def test_native_windows_arm_interpreter_uses_arm_notices(monkeypatch):
    import sysconfig

    monkeypatch.setattr(notices.sys, "platform", "win32")
    monkeypatch.setattr(notices.platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-arm64")
    monkeypatch.setenv("CLEANTAKE_NATIVE_ARCH", "arm64")
    assert notices.interpreter_identity()["target"] == "aarch64-pc-windows-msvc"


def test_ci_matrix_architecture_must_match_selected_interpreter(monkeypatch):
    monkeypatch.setattr(notices.sys, "platform", "darwin")
    monkeypatch.setattr(notices.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("CLEANTAKE_NATIVE_ARCH", "x64")
    with pytest.raises(ValueError, match="requested native architecture"):
        notices.interpreter_identity()
