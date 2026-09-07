from __future__ import annotations

import json

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from typer.testing import CliRunner

from cleantake.cli import app
from cleantake.projects import ProjectStore

runner = CliRunner()


def test_help_version_and_doctor_are_usable():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0 and "0.2.0" in version.stdout
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    result = json.loads(doctor.stdout)
    assert result["ffmpeg"]["available"] and result["ffprobe"]["available"]


def test_missing_ffmpeg_has_an_actionable_nonzero_result(monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    output = json.loads(result.stdout)
    assert not output["ffmpeg"]["available"]
    assert "install" in output["ffmpeg"]["action"].lower()


def test_project_commands_create_import_show_and_export_real_audio(tmp_path):
    arguments = ["--workspace", str(tmp_path / "work")]
    created = runner.invoke(app, [*arguments, "create", "First interview"])
    assert created.exit_code == 0, created.output
    pid = json.loads(created.stdout)["id"]
    source = tmp_path / "take.wav"
    sf.write(source, np.linspace(-0.2, 0.2, 48_000), 48_000, subtype="FLOAT")
    imported = runner.invoke(app, [*arguments, "import", pid, str(source)])
    assert imported.exit_code == 0, imported.output
    shown = runner.invoke(app, [*arguments, "show", pid])
    assert json.loads(shown.stdout)["duration_frames"] == 48_000
    exported = runner.invoke(app, [*arguments, "export", pid, "--output", str(tmp_path / "render")])
    assert exported.exit_code == 0, exported.output
    assert sf.info(tmp_path / "render/dialogue.wav").frames == 48_000
    duplicate = runner.invoke(
        app, [*arguments, "export", pid, "--output", str(tmp_path / "render")]
    )
    assert duplicate.exit_code != 0
    assert "exists" in duplicate.output


def test_repair_command_requires_explicit_automatic_acceptance_and_saves_project(tmp_path):
    rate = 48_000
    rng = np.random.default_rng(848)
    clean = (
        sosfilt(
            butter(3, [180, 3800], fs=rate, btype="bandpass", output="sos"),
            rng.normal(size=rate * 6),
        )
        * 0.1
    )
    time = np.arange(len(clean)) / rate
    clean *= 0.15 + 0.85 * np.sin(2 * np.pi * 1.7 * time) ** 2
    damaged = clean.copy()
    damaged[rate * 2 : rate * 3] = 0
    main, backup = tmp_path / "main.wav", tmp_path / "backup.wav"
    sf.write(main, damaged, rate, subtype="FLOAT")
    sf.write(backup, clean * 0.8, rate, subtype="FLOAT")
    arguments = ["--workspace", str(tmp_path / "work"), "repair", str(main), str(backup)]
    reviewed = runner.invoke(app, [*arguments, "--output", str(tmp_path / "review")])
    assert reviewed.exit_code == 0, reviewed.output
    review_result = json.loads(reviewed.stdout)
    assert review_result["accepted"] == 0 and review_result["pending"] > 0
    auto = runner.invoke(
        app, [*arguments, "--output", str(tmp_path / "automatic"), "--accept-confident"]
    )
    assert auto.exit_code == 0, auto.output
    result = json.loads(auto.stdout)
    assert result["accepted"] > 0
    project = ProjectStore(tmp_path / "work/projects").get(result["project_id"])
    assert project.repairs[0].status == "accepted"
    audio, _ = sf.read(tmp_path / "automatic/dialogue.wav")
    assert np.sqrt(np.mean(audio[rate * 2 : rate * 3] ** 2)) > 0.005
    assert len(audio) == len(damaged)


def test_invalid_media_returns_nonzero_without_partial_source(tmp_path):
    workspace = tmp_path / "work"
    created = runner.invoke(app, ["--workspace", str(workspace), "create", "Bad file"])
    pid = json.loads(created.stdout)["id"]
    bad = tmp_path / "bad.wav"
    bad.write_text("not media")
    result = runner.invoke(app, ["--workspace", str(workspace), "import", pid, str(bad)])
    assert result.exit_code != 0
    assert ProjectStore(workspace / "projects").get(pid).sources == []


def test_manual_cli_decisions_are_editable_and_undoable(tmp_path):
    workspace = tmp_path / "work"
    store = ProjectStore(workspace / "projects")
    project = store.create("Manual")
    for index in range(2):
        path = tmp_path / f"{index}.wav"
        sf.write(path, np.linspace(-0.1, 0.1 + index * 0.1, 48_000), 48_000)
        source = store.import_source(project.id, path)
    args = ["--workspace", str(workspace)]
    alignment = runner.invoke(app, [*args, "source", project.id, source.id, "--offset", "0"])
    assert alignment.exit_code == 0, alignment.output
    added = runner.invoke(
        app,
        [
            *args,
            "add-repair",
            project.id,
            source.id,
            "--start",
            "0.2",
            "--end",
            "0.4",
            "--fade",
            "5",
        ],
    )
    assert added.exit_code == 0, added.output
    repair = store.get(project.id).repairs[0]
    assert (repair.start_frame, repair.end_frame) == (9600, 19200)
    accepted = runner.invoke(app, [*args, "edit", project.id, repair.id, "--status", "accepted"])
    assert accepted.exit_code == 0, accepted.output
    assert store.get(project.id).repairs[0].status == "accepted"
    assert runner.invoke(app, [*args, "undo", project.id]).exit_code == 0
    assert store.get(project.id).repairs[0].status == "proposed"
    assert runner.invoke(app, [*args, "redo", project.id]).exit_code == 0
    assert store.get(project.id).repairs[0].status == "accepted"


def test_cli_does_not_modify_a_workspace_owned_by_the_running_studio(tmp_path):
    from cleantake.server.jobs import WorkspaceLease

    workspace = tmp_path / "work"
    workspace.mkdir()
    lease = WorkspaceLease(workspace)
    try:
        result = runner.invoke(app, ["--workspace", str(workspace), "create", "Concurrent"])
        assert result.exit_code != 0
        assert "already open" in result.output
        assert ProjectStore(workspace / "projects").list() == []
    finally:
        lease.close()
    result = runner.invoke(app, ["--workspace", str(workspace), "create", "Available"])
    assert result.exit_code == 0


def test_corrupt_or_unsupported_archives_have_actionable_cli_errors(tmp_path):
    import struct
    import zipfile

    workspace = tmp_path / "work"
    project = ProjectStore(workspace / "projects").create("Archive validation")
    for mode in ("unknown-method", "corrupt-deflate"):
        archive = tmp_path / f"{mode}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.writestr("project.json", project.model_dump_json())
        data = bytearray(archive.read_bytes())
        if mode == "unknown-method":
            struct.pack_into("<H", data, 8, 99)
            struct.pack_into("<H", data, data.index(b"PK\x01\x02") + 10, 99)
        else:
            name_size, extra_size = struct.unpack_from("<HH", data, 26)
            data[30 + name_size + extra_size] = 255
        archive.write_bytes(data)
        result = runner.invoke(app, ["--workspace", str(workspace), "open-archive", str(archive)])
        assert result.exit_code == 1
        assert "CleanTake:" in result.output
        assert "archive" in result.output.lower()
        assert "Traceback" not in result.output
