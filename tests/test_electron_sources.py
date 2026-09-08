"""The Electron source supplement is pinned to the distributed runtime."""

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "stage_electron_sources", Path(__file__).parents[1] / "scripts/stage_electron_sources.py"
)
assert SPEC and SPEC.loader
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    root = tmp_path / "repo"
    (root / "desktop").mkdir(parents=True)
    lock = root / "desktop/package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/electron": {"version": "44.2.0"}}}))
    cache = tmp_path / "cache"
    cache.mkdir()
    archive = cache / "covered.tar.gz"
    with tarfile.open(archive, "w:gz") as out:
        for name, data in [("COPYING", b"unmodified license\r\n"), ("source.c", b"source")]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            out.addfile(member, io.BytesIO(data))
    readme = b"Exact rebuild instructions\n"
    (config / "README.md").write_bytes(readme)
    value = {
        "schema_version": 1, "electron_version": "44.2.0", "chromium_version": "152.0.7977.76",
        "electron_revision": "a" * 40, "chromium_revision": "b" * 40,
        "sources": [{"name": archive.name, "url": "https://example.invalid/source.tar.gz",
                     **pin(archive.read_bytes()), "licenses": [
                         {"member": "COPYING", "destination": "covered/COPYING",
                          **pin(b"unmodified license\r\n")}
                     ]}],
        "recipe_files": {"README.md": pin(readme)}, "native_distributions": {},
    }
    (config / "pins.json").write_text(json.dumps(value))
    monkeypatch.setattr(stage, "CONFIG", config)
    monkeypatch.setattr(stage, "ROOT", root)
    return tmp_path, cache, value, lock


def test_stage_preserves_exact_source_and_notices_without_network(fixture):
    tmp, cache, _, _ = fixture
    output = tmp / "stage"
    result = stage.stage(output, cache)
    assert result["target"] == "common"
    assert result["electron_version"] == "44.2.0"
    assert (output / "licenses/covered/COPYING").read_bytes() == b"unmodified license\r\n"
    assert (output / "source/upstream/covered.tar.gz").read_bytes() == (
        cache / "covered.tar.gz"
    ).read_bytes()
    assert stage.validate_manifest(output) == result


def test_runtime_version_mismatch_cannot_inherit_source_pins(fixture):
    tmp, cache, _, lock = fixture
    lock.write_text(json.dumps({"packages": {"node_modules/electron": {"version": "44.2.1"}}}))
    with pytest.raises(stage.SourceError, match="Electron version"):
        stage.stage(tmp / "stage", cache)
    assert not (tmp / "stage").exists()


def test_archive_tampering_fails_before_publishing_stage(fixture):
    tmp, cache, _, _ = fixture
    (cache / "covered.tar.gz").write_bytes(b"tampered")
    with pytest.raises(stage.SourceError, match="SHA-256"):
        stage.stage(tmp / "stage", cache)
    assert not (tmp / "stage").exists()


def test_manifest_cannot_bless_replaced_source_by_rehashing_it(fixture):
    tmp, cache, _, _ = fixture
    output = tmp / "stage"
    value = stage.stage(output, cache)
    payload = output / "source/upstream/covered.tar.gz"
    payload.write_bytes(b"replacement")
    value["files"]["source/upstream/covered.tar.gz"] = pin(b"replacement")
    (output / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(stage.SourceError, match="trusted|pinned"):
        stage.validate_manifest(output)


def test_inventory_rejects_extra_missing_and_outside_files(fixture):
    tmp, cache, _, _ = fixture
    output = tmp / "stage"
    stage.stage(output, cache)
    extra = output / "source/extra"
    extra.write_text("extra")
    with pytest.raises(stage.SourceError, match="inventory"):
        stage.validate_manifest(output)
    extra.unlink()
    (output / "licenses/covered/COPYING").unlink()
    with pytest.raises(stage.SourceError, match="inventory"):
        stage.validate_manifest(output)
    with pytest.raises(stage.SourceError, match="path"):
        stage.safe_path("../outside")


def test_license_symlink_is_never_followed(tmp_path):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as out:
        member = tarfile.TarInfo("COPYING")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        out.addfile(member)
    with pytest.raises(stage.SourceError, match="regular"):
        stage.license_bytes(archive, "COPYING")


def test_existing_stage_is_preserved(fixture):
    tmp, cache, _, _ = fixture
    output = tmp / "stage"
    stage.stage(output, cache)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(stage.SourceError, match="exists"):
        stage.stage(output, cache)
    assert (output / "manifest.json").read_bytes() == before


def test_source_recipe_edit_requires_explicit_pin_update(fixture):
    tmp, cache, _, _ = fixture
    (stage.CONFIG / "README.md").write_text("changed instructions")
    with pytest.raises(stage.SourceError, match="SHA-256"):
        stage.stage(tmp / "stage", cache)


def test_exact_chromium_deps_and_electron_patch_are_preserved():
    pins = stage.load_pins()
    metadata = stage.CONFIG / "upstream-metadata"
    chromium_deps = (metadata / "chromium/DEPS").read_text()
    electron_deps = (metadata / "electron/DEPS").read_text()
    assert pins["chromium_version"] in electron_deps
    assert pins["ffmpeg_revision"] in chromium_deps
    ffmpeg = next(item for item in pins["sources"] if item["root"] == "third_party/ffmpeg")
    assert ffmpeg["revision"] == pins["ffmpeg_revision"]
    patches = metadata / "electron/patches/ffmpeg"
    names = (patches / ".patches").read_text().splitlines()
    assert names == ["link_with_loader_path.patch"]
    assert "@loader_path/libffmpeg.dylib" in (patches / names[0]).read_text()
    for name, pin_value in pins["recipe_files"].items():
        stage.verify_file(stage.CONFIG / name, pin_value)


@pytest.mark.parametrize("target", [
    "mac/arm64", "mac/x64", "linux/arm64", "linux/x64", "win/arm64", "win/x64",
])
def test_supplied_ffmpeg_target_uses_the_distributed_license_configuration(target):
    metadata = stage.CONFIG / "upstream-metadata"
    configuration = (metadata / f"ffmpeg/chromium/config/Chrome/{target}/config.h").read_text()
    for flag in ["GPL", "GPLV3", "VERSION3", "NONFREE"]:
        assert f"#define CONFIG_{flag} 0\n" in configuration
    assert '#define CONFIG_LIBOPUS 1\n' in configuration
    assert 'is_component_ffmpeg = true' in (metadata / "electron/build/args/release.gn").read_text()
    assert 'ffmpeg_branding = "Chrome"' in (metadata / "electron/build/args/all.gn").read_text()
