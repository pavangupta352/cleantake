from __future__ import annotations

import shutil
import subprocess
import sys
import time

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from cleantake.cli import app
from cleantake.media import MediaError, _binary, decode_to_cache, inspect_media


def test_frozen_media_uses_absolute_bundle_path_with_empty_search_path(tmp_path, monkeypatch):
    bundle = tmp_path / "Bundle é" / "_internal"
    tools = bundle / "media"
    tools.mkdir(parents=True)
    source = shutil.which("ffprobe")
    assert source
    target = tools / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    shutil.copy2(source, target)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("PATH", "")
    assert _binary("ffprobe") == str(target.resolve())


def test_frozen_missing_media_never_falls_back_to_host_tools(tmp_path, monkeypatch):
    assert shutil.which("ffprobe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(MediaError, match="[Bb]undled.*ffprobe"):
        _binary("ffprobe")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert '"available": false' in result.stdout
    assert "reinstall" in result.stdout.lower()


def test_frozen_corrupt_media_has_actionable_error_without_host_fallback(tmp_path, monkeypatch):
    tools = tmp_path / "media"
    tools.mkdir()
    target = tools / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    target.write_bytes(b"not an executable")
    target.chmod(0o755)
    audio = tmp_path / "source.wav"
    sf.write(audio, np.zeros(4800), 48_000)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(MediaError, match="run|reinstall"):
        inspect_media(audio)


def test_real_wavpack_import_uses_actual_wv_demuxer_name(tmp_path):
    source = tmp_path / "source.wav"
    packed = tmp_path / "recording.wv"
    cache = tmp_path / "cache.f32le"
    audio = (np.sin(np.arange(48_000) * 0.07) * 0.2).astype("float32")
    sf.write(source, audio, 48_000, subtype="PCM_16")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), "-c:a", "wavpack", str(packed)],
        check=True,
    )
    result = decode_to_cache(packed, cache)
    assert result.container_name == "wv"
    assert result.frames == 48_000
    expected, _ = sf.read(source, dtype="float32")
    assert np.array_equal(np.fromfile(cache, dtype="<f4"), expected)


def test_finishing_missing_frozen_tool_cannot_use_host_ffmpeg(tmp_path, monkeypatch):
    from cleantake.exports import ExportError, finish_audio

    source = tmp_path / "source.wav"
    sf.write(source, np.sin(np.arange(96_000) * 0.07) * 0.1, 48_000)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(ExportError, match="[Bb]undled.*ffmpeg"):
        finish_audio(source, tmp_path / "finished.wav")


def test_missing_frozen_decoder_does_not_leave_a_partial_cache(tmp_path, monkeypatch):
    import cleantake.media as media

    installed_probe = _binary("ffprobe")
    resolver = media.media_binary
    # Keep a package-manager launcher beside its installation. This regression
    # targets missing decoder cleanup; the separate frozen lookup tests cover
    # probe isolation and missing-tool refusal.
    monkeypatch.setattr(
        media, "media_binary", lambda name: installed_probe if name == "ffprobe" else resolver(name)
    )
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(4800), 48_000)
    cache = tmp_path / "cache" / "audio.f32le"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(MediaError, match="[Bb]undled.*ffmpeg"):
        decode_to_cache(source, cache)
    assert not cache.exists()
    assert not list(cache.parent.iterdir())


def _windows_child_tree(pid_file):
    from cleantake.server.jobs import _guard_worker_lifetime

    _guard_worker_lifetime()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    from pathlib import Path

    temporary = Path(pid_file).with_suffix(".tmp")
    temporary.write_text(str(child.pid))
    temporary.replace(pid_file)
    child.wait()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires the actual Windows process APIs")
@pytest.mark.parametrize("helper_failure", [None, "unavailable", "timeout"])
def test_windows_hidden_helpers_and_empty_path_tree_cancellation(
    tmp_path, monkeypatch, helper_failure
):
    import ctypes
    import multiprocessing

    from cleantake.runtime import subprocess_options
    from cleantake.server.jobs import JobManager

    result = subprocess.run(
        [sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"],
        capture_output=True,
        text=True,
        check=True,
        **subprocess_options(),
    )
    assert result.stdout.strip() == "0"
    pid_file = tmp_path / "child.pid"
    worker = multiprocessing.get_context("spawn").Process(
        target=_windows_child_tree,
        args=(str(pid_file),),
    )
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        child_pid = int(pid_file.read_text())
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, child_pid)
        assert handle
        try:
            monkeypatch.setenv("PATH", "")
            if helper_failure:

                def unavailable(*args, **kwargs):
                    if helper_failure == "timeout":
                        raise subprocess.TimeoutExpired("taskkill", 5)
                    raise OSError("taskkill unavailable")

                monkeypatch.setattr("cleantake.server.jobs.subprocess.run", unavailable)
            JobManager._stop(None, worker)
            assert not worker.is_alive()
            assert kernel.WaitForSingleObject(ctypes.c_void_p(handle), 5000) == 0
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join(timeout=5)
        worker.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires actual Windows standard handles")
def test_child_stdin_isolated_while_original_control_pipe_stays_readable():
    import os

    script = '''
import ctypes, multiprocessing, os, subprocess, sys, threading, time
from ctypes import wintypes
from cleantake.runtime import isolated_child_stdin
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetStdHandle.argtypes = [wintypes.DWORD]
kernel.GetStdHandle.restype = wintypes.HANDLE
original = kernel.GetStdHandle(-10)
with isolated_child_stdin():
    assert kernel.GetStdHandle(-10) != original
    received = []
    started = threading.Event()
    def read_control():
        started.set()
        received.append(sys.stdin.readline())
    reader = threading.Thread(target=read_control, daemon=True)
    reader.start()
    assert started.wait(2)
    worker = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(0.01,))
    worker.start()
    try:
        worker.join(5)
        assert worker.exitcode == 0, "Spawn bootstrap stalled on the control pipe"
        assert reader.is_alive() and not received, "Original control read was released"
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(5)
        worker.close()
    child = subprocess.run([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
                           capture_output=True, text=True, timeout=5)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "''", child.stdout
    print("CHILD_READY", flush=True)
    reader.join(5)
    assert received == ["shutdown\\n"], received
assert kernel.GetStdHandle(-10) == original
print("CONTROL_RETAINED", flush=True)
'''
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=dict(os.environ),
    )
    try:
        import queue
        import threading

        messages = queue.Queue()
        threading.Thread(
            target=lambda: messages.put(process.stdout.readline()), daemon=True
        ).start()
        assert messages.get(timeout=10).strip() == "CHILD_READY"
        process.stdin.write("shutdown\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 0, process.stderr.read()
        assert process.stdout.read().strip() == "CONTROL_RETAINED"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
