from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cleantake.media import MediaError, decode_to_cache, inspect_media, sha256_file


def test_decoded_cache_is_synced_with_a_writable_handle_before_publication(tmp_path, monkeypatch):
    import os
    import stat

    source, cache = tmp_path / "source.wav", tmp_path / "cache.f32le"
    samples = np.linspace(-0.2, 0.2, 4800, dtype=np.float32)
    sf.write(source, samples, 48_000, subtype="FLOAT")
    original = source.read_bytes()
    sync = os.fsync
    synchronized_files = []

    def require_writable_file(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            # Windows flushing needs a writable descriptor; a zero-byte write
            # verifies the same requirement on every platform without changing PCM.
            os.write(descriptor, b"")
            synchronized_files.append(descriptor)
        sync(descriptor)

    monkeypatch.setattr(os, "fsync", require_writable_file)
    decoded = decode_to_cache(source, cache)
    assert synchronized_files
    assert decoded.frames == len(samples)
    assert np.array_equal(np.fromfile(cache, dtype="<f4"), samples)
    assert source.read_bytes() == original


def test_playlist_cannot_import_external_local_recordings(tmp_path):
    private = tmp_path / "private.ts"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "aac",
            "-f",
            "mpegts",
            str(private),
        ],
        check=True,
    )
    playlist = tmp_path / "uploaded.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n" + private.as_uri() + "\n#EXT-X-ENDLIST\n"
    )
    for operation in [
        lambda: inspect_media(playlist),
        lambda: decode_to_cache(playlist, tmp_path / "cache.f32le"),
    ]:
        with pytest.raises(MediaError, match="unsupported|readable"):
            operation()
    assert not (tmp_path / "cache.f32le").exists()


def test_remote_playlist_is_rejected_before_any_network_request(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    playlist = tmp_path / "uploaded.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n"
        f"http://127.0.0.1:{server.server_port}/secret.ts\n#EXT-X-ENDLIST\n"
    )
    try:
        with pytest.raises(MediaError):
            inspect_media(playlist)
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _stereo_wav(path: Path, *, sample_rate: int = 44_100, seconds: float = 0.25) -> np.ndarray:
    frames = round(sample_rate * seconds)
    time = np.arange(frames, dtype=np.float64) / sample_rate
    data = np.column_stack(
        [
            0.2 * np.sin(2 * np.pi * 440 * time),
            0.6 * np.sin(2 * np.pi * 880 * time),
        ]
    ).astype(np.float32)
    sf.write(path, data, sample_rate, subtype="FLOAT")
    return data


def test_decode_real_wav_selects_channel_and_creates_disk_backed_48k_mono(tmp_path: Path) -> None:
    """Changing the requested stereo channel must change the decoded mono samples."""

    source = tmp_path / "stéréo source.wav"
    _stereo_wav(source)
    left_cache = tmp_path / "left.f32le"
    right_cache = tmp_path / "right.f32le"

    probe = inspect_media(source)
    left = decode_to_cache(source, left_cache, stream=0, channel=0)
    right = decode_to_cache(source, right_cache, stream=0, channel=1)
    left_samples = np.memmap(left_cache, dtype="<f4", mode="r", shape=(left.frames,))
    right_samples = np.memmap(right_cache, dtype="<f4", mode="r", shape=(right.frames,))

    assert probe.audio_streams[0].sample_rate == 44_100
    assert probe.audio_streams[0].channels == 2
    assert left.sample_rate == right.sample_rate == 48_000
    assert left.channels == right.channels == 1
    assert left.channel_mode == "channel:0"
    assert right.channel_mode == "channel:1"
    assert left.frames == right.frames == 12_000
    assert isinstance(left_samples, np.memmap)
    assert np.sqrt(np.mean(np.square(right_samples))) > 2.5 * np.sqrt(
        np.mean(np.square(left_samples))
    )


@pytest.mark.media
def test_decode_small_ffmpeg_video_uses_its_audio_stream(tmp_path: Path) -> None:
    """A supported video container must yield its real embedded audio metadata and samples."""

    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is not installed")
    wav = tmp_path / "audio.wav"
    _stereo_wav(wav, sample_rate=48_000)
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:r=10:d=0.25",
            "-i",
            str(wav),
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )

    probe = inspect_media(video)
    cache = tmp_path / "video.f32le"
    decoded = decode_to_cache(video, cache, stream=0, channel=None)

    assert probe.container_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert probe.audio_streams[0].codec_name == "aac"
    assert decoded.frames > 10_000
    assert decoded.channel_mode == "downmix"
    assert cache.stat().st_size == decoded.frames * 4


@pytest.mark.parametrize("contents", [b"", b"not media\x00\x01"])
def test_probe_rejects_empty_and_non_media_files(tmp_path: Path, contents: bytes) -> None:
    """Invalid inputs must produce a stable media error rather than a partial cache."""

    path = tmp_path / "bad.bin"
    path.write_bytes(contents)

    with pytest.raises(MediaError, match="audio"):
        inspect_media(path)


def test_media_helpers_reject_symlinks_and_invalid_channel_without_output(tmp_path: Path) -> None:
    """Import cannot follow a symlink or silently choose a nonexistent channel."""

    real = tmp_path / "real.wav"
    _stereo_wav(real)
    linked = tmp_path / "linked.wav"
    linked.symlink_to(real)
    cache = tmp_path / "bad.f32le"

    with pytest.raises(MediaError, match="symbolic link"):
        inspect_media(linked)
    with pytest.raises(MediaError, match="channel"):
        decode_to_cache(real, cache, stream=0, channel=2)

    assert not cache.exists()
    assert len(sha256_file(real)) == 64


def test_decode_rejects_nonfinite_pcm_without_publishing_cache(tmp_path: Path) -> None:
    """NaN source samples cannot cross the finite engine-input boundary."""

    source = tmp_path / "nonfinite.wav"
    samples = np.zeros(4_800, dtype=np.float32)
    samples[2_400] = np.nan
    sf.write(source, samples, 48_000, subtype="FLOAT")
    cache = tmp_path / "nonfinite.f32le"

    with pytest.raises(MediaError, match="non-finite"):
        decode_to_cache(source, cache)

    assert not cache.exists()
