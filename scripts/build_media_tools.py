#!/usr/bin/env python3
"""Build and audit native, standalone LGPL FFmpeg tools from pinned source.

Build-time Python 3.12+, GnuPG, make and a native C toolchain are required.
The resulting programs do not require Python or those build tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import wave
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "packaging" / "ffmpeg"
COMMON_FLAGS = (
    "--disable-autodetect",
    "--disable-gpl",
    "--disable-version3",
    "--disable-nonfree",
    "--disable-shared",
    "--enable-static",
    "--disable-network",
    "--disable-devices",
    "--disable-avdevice",
    "--disable-ffplay",
    "--disable-doc",
    "--disable-debug",
    "--disable-hwaccels",
    "--disable-amf",
    "--disable-audiotoolbox",
    "--disable-cuda-llvm",
    "--disable-cuvid",
    "--disable-ffnvcodec",
    "--disable-nvdec",
    "--disable-nvenc",
    "--disable-d3d11va",
    "--disable-d3d12va",
    "--disable-dxva2",
    "--disable-libdrm",
    "--disable-vaapi",
    "--disable-vdpau",
    "--disable-videotoolbox",
    "--disable-vulkan",
    "--disable-metal",
    "--disable-mediafoundation",
    "--disable-v4l2-m2m",
)


class BuildError(RuntimeError):
    """The source, toolchain, build, or resulting payload failed validation."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_archive(path: Path, pin: dict) -> None:
    if not path.is_file() or path.is_symlink():
        raise BuildError(f"Source must be a regular file: {path.name}")
    if path.stat().st_size != pin["bytes"] or digest(path) != pin["sha256"]:
        raise BuildError(f"Source size/SHA-256 mismatch: {path.name}")


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise BuildError(f"Unsafe path: {name!r}")
    return path


def safe_extract(archive: Path, destination: Path, root: str) -> Path:
    """Validate the entire archive before writing, and never follow archive links."""
    if destination.exists() or destination.is_symlink():
        raise BuildError("Extraction destination already exists")
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        seen: set[str] = set()
        size = 0
        if len(members) > 100_000:
            raise BuildError("Source archive has too many members")
        for member in members:
            name = member.name.rstrip("/") if member.isdir() else member.name
            path = safe_relative(name)
            if path.parts[0] != root or not (member.isdir() or member.isfile()):
                raise BuildError(f"Unsafe archive member: {member.name!r}")
            if name in seen:
                raise BuildError(f"Source archive has duplicate path: {name}")
            seen.add(name)
            size += member.size
            if member.size < 0 or size > 1024 * 1024 * 1024:
                raise BuildError("Source archive expands beyond its size limit")
        try:
            destination.mkdir(parents=True)
            for member in members:
                target = destination / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = source.extractfile(member)
                    if data is None:
                        raise BuildError("Source member has no content")
                    with data, target.open("xb") as out:
                        shutil.copyfileobj(data, out)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
    return destination / root


def download_source(pin: dict, cache: Path, supplied: Path | None = None) -> Path:
    if supplied:
        verify_archive(supplied, pin)
        return supplied.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / pin["archive"]
    if target.exists():
        verify_archive(target, pin)
        return target.resolve()
    handle, temporary = tempfile.mkstemp(prefix="download-", dir=cache)
    try:
        with os.fdopen(handle, "wb") as out:
            request = urllib.request.Request(pin["url"], headers={"User-Agent": "CleanTake-build"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise BuildError("Source download redirected away from HTTPS")
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > pin["bytes"]:
                        raise BuildError("Source download exceeds pinned size")
                    out.write(block)
        verify_archive(Path(temporary), pin)
        os.replace(temporary, target)
        return target.resolve()
    finally:
        Path(temporary).unlink(missing_ok=True)


def run(
    args: list[str | Path],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    input_data: bytes | None = None,
    log: Path | None = None,
    timeout: int = 120,
) -> str:
    command = [str(arg) for arg in args]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildError(f"Could not run {Path(command[0]).name}: {error}") from error
    output = result.stdout.decode("utf-8", errors="replace")
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(output, encoding="utf-8")
    if result.returncode:
        raise BuildError(f"{Path(command[0]).name} exited {result.returncode}:\n{output[-6000:]}")
    return output


def shell_path(path: Path) -> str:
    if sys.platform == "win32":
        return run(["cygpath", "-u", path.resolve()]).strip()
    return str(path.resolve())


def verify_signature(archive: Path, pin: dict, env: dict) -> dict:
    for name, hash_key in (("key", "key_sha256"), ("signature", "signature_sha256")):
        if digest(CONFIG / pin[name]) != pin[hash_key]:
            raise BuildError(f"Pinned FFmpeg {name} has changed")
    # Short isolated home avoids macOS GnuPG agent socket-path limits.
    parent = "/tmp" if sys.platform != "win32" else None
    with tempfile.TemporaryDirectory(prefix="ctff-", dir=parent) as temporary:
        home = Path(temporary)
        home.chmod(0o700)
        base = ["gpg", "--batch", "--no-tty", "--homedir", shell_path(home)]
        run([*base, "--import", shell_path(CONFIG / pin["key"])], env=env)
        result = run(
            [
                *base,
                "--status-fd",
                "1",
                "--verify",
                shell_path(CONFIG / pin["signature"]),
                shell_path(archive),
            ],
            env=env,
        )
        if f"[GNUPG:] VALIDSIG {pin['fingerprint']} " not in result:
            raise BuildError("FFmpeg source was not signed by the pinned release key")
    return {
        "status": "verified",
        "fingerprint": pin["fingerprint"],
        "signature_sha256": pin["signature_sha256"],
        "key_sha256": pin["key_sha256"],
    }


def native_target() -> tuple[str, str]:
    family = {"darwin": "macos", "win32": "windows", "linux": "linux"}.get(sys.platform)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        platform.machine().lower()
    )
    if not family or not arch:
        raise BuildError("Only native macOS, Windows and Linux x64/ARM64 builds are supported")
    if family == "windows":
        required = "CLANGARM64" if arch == "arm64" else "UCRT64"
        if os.environ.get("MSYSTEM") != required:
            raise BuildError(f"Windows {arch} must build inside the MSYS2 {required} shell")
    return family, arch


def build_environment() -> dict:
    env = os.environ.copy()
    for key in (
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
        "LIBRARY_PATH",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "PKG_CONFIG_PATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "CC",
        "CXX",
        "AR",
        "NM",
        "STRIP",
        "REALGCC",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "PKG_CONFIG_LIBDIR",
        "PKG_CONFIG_SYSROOT_DIR",
    ):
        env.pop(key, None)
    env.update({"LC_ALL": "C", "LANG": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "1786492800"})
    return env


def toolchain(
    family: str, arch: str, work: Path, env: dict, pins: dict, cache: Path, jobs: int
) -> tuple[list[str], dict, Path | None]:
    ffarch = "aarch64" if arch == "arm64" else "x86_64"
    info: dict = {"make": run(["make", "--version"], env=env).splitlines()[0]}
    if arch == "x64":
        info["nasm"] = run(["nasm", "-v"], env=env).strip()
    if family == "macos":
        sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], env=env).strip()
        info["sdk"] = run(["xcrun", "--sdk", "macosx", "--show-sdk-version"], env=env).strip()
        info["minimum_os"] = "14.0"
        cc = run(["xcrun", "--find", "clang"], env=env).strip()
        flags = f"-arch {'arm64' if arch == 'arm64' else 'x86_64'} -isysroot {sdk}"
        flags += " -mmacosx-version-min=14.0"
        args = [
            "--target-os=darwin",
            f"--arch={ffarch}",
            f"--cc={cc}",
            f"--extra-cflags={flags}",
            f"--extra-ldflags={flags}",
            f"--host-cflags={flags}",
            f"--host-ldflags={flags}",
        ]
        info["compiler"] = run([cc, "--version"], env=env).strip()
        info["linker"] = run(["xcrun", "ld", "-v"], env=env).strip()
        return args, info, None
    if family == "windows":
        cc = "clang" if arch == "arm64" else "gcc"
        args = [
            "--target-os=mingw32",
            f"--arch={ffarch}",
            f"--cc={cc}",
            "--disable-pthreads",
            "--enable-w32threads",
        ]
        if arch == "arm64":
            args += [
                "--cxx=clang++",
                "--ld=clang",
                "--ar=llvm-ar",
                "--nm=llvm-nm",
                "--ranlib=llvm-ranlib",
                "--strip=llvm-strip",
                "--extra-ldflags=-static -rtlib=compiler-rt -Wl,--no-insert-timestamp",
            ]
        else:
            args += ["--extra-ldflags=-static -static-libgcc -Wl,--no-insert-timestamp"]
        info["compiler"] = run([cc, "--version"], env=env).strip()
        info["packages"] = run(["pacman", "-Q"], env=env).splitlines()
        return args, info, None
    archive = download_source(pins["musl"], cache)
    source = safe_extract(archive, work / "musl-source", pins["musl"]["root"])
    prefix = work / "musl"
    info["compiler"] = run(["gcc", "--version"], env=env).strip()
    info["linker"] = run(["ld", "--version"], env=env).splitlines()[0]
    run(
        ["sh", "configure", f"--prefix={prefix}", "--disable-shared", "CC=gcc"],
        cwd=source,
        env=env,
        log=work / "logs/musl-configure.txt",
        timeout=600,
    )
    run(["make", f"-j{jobs}"], cwd=source, env=env, log=work / "logs/musl-build.txt", timeout=3600)
    run(["make", "install"], cwd=source, env=env, log=work / "logs/musl-install.txt", timeout=600)
    env["PATH"] = str(prefix / "bin") + os.pathsep + env["PATH"]
    return (
        [
            "--target-os=linux",
            f"--arch={ffarch}",
            "--cc=musl-gcc",
            "--host-cc=gcc",
            "--extra-ldflags=-static -static-libgcc",
        ],
        info,
        archive,
    )


def binary_architecture(path: Path, family: str, arch: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if family == "macos":
            expected = 0x0100000C if arch == "arm64" else 0x01000007
            valid = (
                len(header) == 64
                and header[:4] == b"\xcf\xfa\xed\xfe"
                and struct.unpack_from("<I", header, 4)[0] == expected
            )
        elif family == "linux":
            expected = 183 if arch == "arm64" else 62
            valid = (
                len(header) == 64
                and header[:6] == b"\x7fELF\x02\x01"
                and struct.unpack_from("<H", header, 18)[0] == expected
            )
        else:
            valid = False
            if header[:2] == b"MZ" and len(header) == 64:
                stream.seek(struct.unpack_from("<I", header, 60)[0])
                pe = stream.read(6)
                expected = 0xAA64 if arch == "arm64" else 0x8664
                valid = (
                    pe[:4] == b"PE\0\0"
                    and len(pe) == 6
                    and struct.unpack_from("<H", pe, 4)[0] == expected
                )
    if not valid:
        raise BuildError(f"Wrong native executable architecture: {path.name} ({family}-{arch})")


def audit_dependencies(path: Path, family: str) -> dict:
    if family == "macos":
        output = run(["otool", "-L", path])
        libraries = [line.strip().split(" (", 1)[0] for line in output.splitlines()[1:]]
        if not libraries or any(
            not item.startswith(("/usr/lib/", "/System/Library/")) for item in libraries
        ):
            raise BuildError(f"Non-system macOS library in {path.name}: {libraries}")
        commands = run(["otool", "-l", path])
        minimum = re.search(r"\bminos\s+(\S+)", commands)
        if not minimum or minimum[1] != "14.0":
            raise BuildError(f"Unexpected macOS deployment target in {path.name}")
        return {"libraries": libraries, "minimum_os": minimum[1]}
    if family == "linux":
        dynamic = run(["readelf", "-d", path])
        program = run(["readelf", "-l", path])
        if "(NEEDED)" in dynamic or "INTERP" in program:
            raise BuildError(f"Linux binary is not standalone static: {path.name}")
        return {"libraries": [], "interpreter": None, "linkage": "static"}
    inspector = "llvm-objdump" if shutil.which("llvm-objdump") else "objdump"
    output = run([inspector, "-p", path])
    libraries = re.findall(r"DLL Name:\s*(\S+)", output)
    allowed = {
        "advapi32.dll",
        "bcrypt.dll",
        "crypt32.dll",
        "kernel32.dll",
        "msvcrt.dll",
        "ntdll.dll",
        "ole32.dll",
        "psapi.dll",
        "secur32.dll",
        "shell32.dll",
        "shlwapi.dll",
        "user32.dll",
        "ucrtbase.dll",
        "ws2_32.dll",
    }
    if not libraries or any(
        item.lower() not in allowed and not item.lower().startswith("api-ms-win-")
        for item in libraries
    ):
        raise BuildError(f"Unexpected Windows runtime dependency in {path.name}: {libraries}")
    return {"libraries": libraries}


def runtime_environment() -> dict:
    env = build_environment()
    env["PATH"] = (
        str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        if sys.platform == "win32"
        else "/usr/bin:/bin"
    )
    return env


def probe_media(ffmpeg: Path, ffprobe: Path, destination: Path) -> dict:
    """Exercise actual demuxing, channel selection, resampling and two-pass finishing."""
    env = runtime_environment()
    destination.mkdir(parents=True)
    wav = destination / "stereo source.wav"
    rate, frames = 44100, 44100 * 4
    pcm = b"".join(
        struct.pack(
            "<hh",
            round(8000 * math.sin(2 * math.pi * 440 * n / rate)),
            round(4000 * math.sin(2 * math.pi * 660 * n / rate)),
        )
        for n in range(frames)
    )
    with wave.open(str(wav), "wb") as out:
        out.setparams((2, 2, rate, frames, "NONE", "not compressed"))
        out.writeframes(pcm)
    formats = [
        ("flac", "flac", []),
        ("wv", "wavpack", []),
        ("m4a", "aac", []),
        ("aiff", "pcm_s16be", []),
        ("ogg", "opus", ["-strict", "-2", "-ar", "48000"]),
        ("oga", "vorbis", ["-strict", "-2"]),
    ]
    checked = []
    for extension, codec, extra in formats:
        target = destination / f"encoded.{extension}"
        run(
            [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", wav, *extra, "-c:a", codec, target],
            env=env,
        )
        result = json.loads(
            run(
                [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", target],
                env=env,
            )
        )
        if result["streams"][0]["codec_type"] != "audio":
            raise BuildError(f"Encoded {extension} has no audio stream")
        if extension == "wv" and result["format"]["format_name"] != "wv":
            raise BuildError("WavPack did not expose its required wv demuxer")
        decoded = destination / f"decoded-{extension}.f32"
        run(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                target,
                "-map",
                "0:a:0",
                "-vn",
                "-af",
                "pan=mono|c0=c1",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_f32le",
                "-f",
                "f32le",
                decoded,
            ],
            env=env,
        )
        if not 190000 * 4 <= decoded.stat().st_size <= 194000 * 4:
            raise BuildError(f"Unexpected decoded duration for {extension}")
        checked.append(extension)
    fixture_manifest = json.loads((CONFIG / "fixtures/manifest.json").read_text(encoding="utf-8"))
    fixture_formats = []
    for name, pin in fixture_manifest["files"].items():
        fixture = CONFIG / "fixtures" / safe_relative(name)
        verify_archive(fixture, pin)
        decoded = destination / f"fixture-{name}.f32"
        run(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                fixture,
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_f32le",
                "-f",
                "f32le",
                decoded,
            ],
            env=env,
        )
        samples = [sample[0] for sample in struct.iter_unpack("<f", decoded.read_bytes())]
        if (
            not 47000 <= len(samples) <= 49000
            or not all(map(math.isfinite, samples))
            or not 0.1 < math.sqrt(sum(value * value for value in samples) / len(samples)) < 0.3
        ):
            raise BuildError(f"Invalid decoded audio for fixture {name}")
        fixture_formats.append(name)
    # Raw RGB is a demuxer, so fixture creation does not require the lavfi capture device.
    video = destination / "video.mov"
    run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            "16x16",
            "-framerate",
            "1",
            "-i",
            "pipe:0",
            "-i",
            wav,
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            video,
        ],
        env=env,
        input_data=bytes([20, 40, 60]) * 16 * 16 * 4,
    )
    streams = json.loads(
        run([ffprobe, "-v", "error", "-show_streams", "-of", "json", video], env=env)
    )["streams"]
    if {stream["codec_type"] for stream in streams} != {"audio", "video"}:
        raise BuildError("Video-container import did not preserve both stream types")
    run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            video,
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "pan=mono|c0=c1,aresample=48000",
            "-f",
            "null",
            "-",
        ],
        env=env,
    )
    measurement = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            wav,
            "-af",
            "loudnorm=I=-16:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        env=env,
    )
    start = measurement.rfind("{")
    stats = json.loads(measurement[start : measurement.rfind("}") + 1])
    if not all(
        math.isfinite(float(stats[key]))
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    ):
        raise BuildError("Loudness measurement returned invalid statistics")
    filters = (
        "loudnorm=I=-16:TP=-1:LRA=11:linear=true"
        f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']},aresample=48000,apad,atrim=end_sample=192000"
    )
    finished = destination / "finished.wav"
    run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            wav,
            "-af",
            filters,
            "-c:a",
            "pcm_f32le",
            finished,
        ],
        env=env,
    )
    result = json.loads(
        run([ffprobe, "-v", "error", "-show_streams", "-of", "json", finished], env=env)
    )["streams"][0]
    if result["sample_rate"] != "48000" or int(result["duration_ts"]) != 192000:
        raise BuildError("Finishing changed the required sample rate or sample count")
    measured = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            finished,
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        env=env,
    )
    integrated = re.findall(r"\bI:\s*(-?[\d.]+)\s+LUFS", measured)
    if not integrated or abs(float(integrated[-1]) + 16) > 0.5:
        raise BuildError("Independent ebur128 measurement missed the finishing target")
    return {
        "generated_audio_formats": checked,
        "fixed_audio_fixtures": fixture_formats,
        "video": "mov/mpeg4/aac",
        "channel_selection": "second channel to mono, 44100 to 48000 Hz",
        "finishing_samples": 192000,
        "integrated_lufs": float(integrated[-1]),
        "runtime_path": "operating-system directories only",
    }


def check_license(notice: str) -> None:
    normalized = " ".join(notice.split())
    if "GNU Lesser General Public License" not in normalized or "version 2.1" not in normalized:
        raise BuildError("FFmpeg did not report LGPL-2.1-or-later")


def capabilities(binary: Path) -> dict:
    env = runtime_environment()
    results = {
        option: run([binary, "-hide_banner", f"-{option}"], env=env)
        for option in (
            "version",
            "buildconf",
            "L",
            "decoders",
            "demuxers",
            "encoders",
            "muxers",
            "filters",
            "protocols",
            "hwaccels",
        )
    }
    if not results["version"].startswith("ffmpeg version 9.0.1 "):
        raise BuildError("Unexpected FFmpeg version")
    check_license(results["L"])
    if results["hwaccels"].strip() != "Hardware acceleration methods:":
        raise BuildError("FFmpeg unexpectedly exposes a hardware acceleration backend")
    for name in ("loudnorm", "ebur128", "aresample", "apad", "atrim", "pan"):
        if not re.search(rf"^\s*[.A-Z]+\s+{name}\s", results["filters"], re.MULTILINE):
            raise BuildError(f"Required filter missing: {name}")
    protocols = {
        line.strip() for line in results["protocols"].splitlines() if line.startswith("  ")
    }
    if not {"file", "pipe"} <= protocols or any(
        name in protocols for name in ("http", "https", "tcp", "udp", "tls", "rtmp")
    ):
        raise BuildError("Unexpected FFmpeg protocol configuration")
    return results


def copy_licenses(source: Path, destination: Path, family: str, arch: str, work: Path) -> None:
    ffmpeg = destination / "FFmpeg"
    ffmpeg.mkdir(parents=True)
    for original in [source / "LICENSE.md", *sorted(source.glob("COPYING.*"))]:
        shutil.copy2(original, ffmpeg / original.name)
    # Preserve all source license texts, including notices for inactive upstream components.
    if family == "linux":
        shutil.copy2(work / "musl-source/musl-1.2.6/COPYRIGHT", destination / "musl-COPYRIGHT")
    if family in ("linux", "windows", "macos"):
        extras = CONFIG / "licenses"
        names = (
            ["LLVM-compiler-rt-LICENSE.txt"]
            if family == "macos" or (family == "windows" and arch == "arm64")
            else ["GCC-COPYING.RUNTIME", "GCC-COPYING3"]
        )
        for name in names:
            shutil.copy2(extras / name, destination / name)
    if family == "windows":
        prefix = run(["cygpath", "-w", os.environ["MINGW_PREFIX"]]).strip()
        candidates = Path(prefix) / "share/licenses"
        runtime = destination / "MSYS2-toolchain"
        runtime.mkdir()
        selected = [
            path
            for path in candidates.iterdir()
            if any(
                token in path.name.lower()
                for token in ("gcc", "mingw", "compiler-rt", "llvm", "clang")
            )
        ]
        if not selected:
            raise BuildError("MSYS2 runtime license files were not found")
        for path in selected:
            if path.is_dir():
                shutil.copytree(path, runtime / path.name)
            else:
                shutil.copy2(path, runtime / path.name)


def file_records(directory: Path, roots: tuple[str, ...]) -> dict:
    return {
        path.relative_to(directory).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for name in roots
        for path in sorted((directory / name).rglob("*"))
        if path.is_file()
    }


def validate_manifest(directory: Path) -> dict:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise BuildError("Unsupported media manifest version")
        files = manifest["files"]
        if "licenses/FFmpeg/COPYING.LGPLv2.1" not in files:
            raise BuildError("Manifest missing required FFmpeg license")
        suffix = ".exe" if manifest["target"].startswith("windows-") else ""
        for name in (f"bin/ffmpeg{suffix}", f"bin/ffprobe{suffix}"):
            if name not in files:
                raise BuildError(f"Manifest missing required executable: {name}")
        for name, record in files.items():
            relative = safe_relative(name)
            if relative.parts[0] not in ("bin", "licenses"):
                raise BuildError(f"Unexpected manifest path: {name}")
            path = directory
            for part in relative.parts:
                path /= part
                if path.is_symlink():
                    raise BuildError(f"Bundle contains symlink: {name}")
            if not path.is_file() or path.stat().st_size != record["bytes"]:
                raise BuildError(f"Missing or changed media payload: {name}")
            if digest(path) != record["sha256"]:
                raise BuildError(f"SHA-256 mismatch for media payload: {name}")
        actual = set()
        for root in ("bin", "licenses"):
            base = directory / root
            if base.is_symlink():
                raise BuildError(f"Bundle contains symlink: {root}")
            for path in base.rglob("*"):
                relative = path.relative_to(directory).as_posix()
                if path.is_symlink():
                    raise BuildError(f"Bundle contains symlink: {relative}")
                if path.is_file():
                    actual.add(relative)
        if actual != set(files):
            raise BuildError(f"Manifest has unrecorded payload: {sorted(actual - set(files))}")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BuildError(f"Invalid media manifest: {error}") from error


def build(output: Path, cache: Path, supplied: Path | None, jobs: int, work: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise BuildError("Output already exists; choose a new directory or use --verify")
    family, arch = native_target()
    pins = json.loads((CONFIG / "sources.json").read_text(encoding="utf-8"))
    env = build_environment()
    archive = download_source(pins["ffmpeg"], cache, supplied)
    signature = verify_signature(archive, pins["ffmpeg"], env)
    print(f"Verified FFmpeg {pins['ffmpeg']['version']}; building {family}-{arch}.", flush=True)
    source = safe_extract(archive, work / "ffmpeg-source", pins["ffmpeg"]["root"])
    platform_flags, compiler, musl_archive = toolchain(family, arch, work, env, pins, cache, jobs)
    flags = [*COMMON_FLAGS, *platform_flags]
    run(
        ["bash" if family == "windows" else "sh", "configure", *flags],
        cwd=source,
        env=env,
        log=work / "logs/ffmpeg-configure.txt",
        timeout=600,
    )
    suffix = ".exe" if family == "windows" else ""
    run(
        ["make", f"-j{jobs}", f"ffmpeg{suffix}", f"ffprobe{suffix}"],
        cwd=source,
        env=env,
        log=work / "logs/ffmpeg-build.txt",
        timeout=7200,
    )
    stage = work / "payload"
    (stage / "bin").mkdir(parents=True)
    audits = {}
    for tool in ("ffmpeg", "ffprobe"):
        executable = stage / "bin" / f"{tool}{suffix}"
        shutil.copy2(source / f"{tool}{suffix}", executable)
        executable.chmod(0o755)
        binary_architecture(executable, family, arch)
        audits[tool] = audit_dependencies(executable, family)
    ffmpeg, ffprobe = stage / "bin" / f"ffmpeg{suffix}", stage / "bin" / f"ffprobe{suffix}"
    available = capabilities(ffmpeg)
    probe_version = run([ffprobe, "-version"], env=runtime_environment()).splitlines()[0]
    if not probe_version.startswith("ffprobe version 9.0.1 "):
        raise BuildError("Unexpected FFprobe version")
    smoke = probe_media(ffmpeg, ffprobe, work / "media-probes")
    copy_licenses(source, stage / "licenses", family, arch, work)
    provenance = stage / "source"
    upstream = provenance / "upstream"
    upstream.mkdir(parents=True)
    shutil.copy2(archive, upstream / archive.name)
    for name in (pins["ffmpeg"]["key"], pins["ffmpeg"]["signature"]):
        shutil.copy2(CONFIG / name, upstream / name)
    if musl_archive:
        shutil.copy2(musl_archive, upstream / musl_archive.name)
    (provenance / "scripts").mkdir()
    shutil.copy2(Path(__file__), provenance / "scripts/build_media_tools.py")
    shutil.copytree(CONFIG, provenance / "packaging/ffmpeg")
    results = provenance / "results"
    results.mkdir()
    for name in ("config.h", "config_components.h", "ffbuild/config.mak"):
        text = (source / name).read_text(encoding="utf-8")
        # Keep build-path placeholders stable and do not publish developer checkout paths.
        text = text.replace(str(work), "$BUILD_ROOT").replace(shell_path(work), "$BUILD_ROOT")
        (results / Path(name).name).write_text(text, encoding="utf-8")
    normalized_flags = [flag.replace(str(work), "$BUILD_ROOT") for flag in flags]
    available = {name: value.replace(str(work), "$BUILD_ROOT") for name, value in available.items()}
    write_json(results / "capabilities.json", available)
    manifest = {
        "schema_version": 1,
        "target": f"{family}-{arch}",
        "ffmpeg_version": "9.0.1",
        "license": "LGPL-2.1-or-later",
        "source": pins["ffmpeg"],
        "source_signature": signature,
        "patches": [],
        "configure_arguments": normalized_flags,
        "toolchain": compiler,
        "runtime_dependencies": audits,
        "smoke": smoke,
        "source_date_epoch": env["SOURCE_DATE_EPOCH"],
        "files": file_records(stage, ("bin", "licenses")),
    }
    if musl_archive:
        manifest["musl_source"] = pins["musl"]
    write_json(stage / "manifest.json", manifest)
    write_json(results / "build-manifest.json", manifest)
    write_json(
        provenance / "SOURCE-MANIFEST.json",
        {
            "schema_version": 1,
            "target": manifest["target"],
            "files": file_records(provenance, ("upstream", "scripts", "packaging", "results")),
        },
    )
    validate_manifest(stage)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Copy to an adjacent temporary directory, then publish only a completely verified bundle.
    with tempfile.TemporaryDirectory(prefix=".media-stage-", dir=output.parent) as temporary:
        adjacent = Path(temporary) / "payload"
        shutil.copytree(stage, adjacent)
        validate_manifest(adjacent)
        (adjacent / "manifest.json").chmod(0o444)
        adjacent.rename(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New validated media bundle directory"
    )
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/native/downloads")
    parser.add_argument(
        "--source-archive", type=Path, help="Use this pinned FFmpeg archive without download"
    )
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 8))
    parser.add_argument(
        "--work-dir", type=Path, help="New directory retaining build logs and intermediates"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify an existing bundle without rebuilding"
    )
    args = parser.parse_args()
    try:
        if args.jobs < 1 or args.jobs > 128:
            raise BuildError("--jobs must be between 1 and 128")
        if args.verify:
            manifest = validate_manifest(args.output.resolve())
        elif args.work_dir:
            args.work_dir.mkdir(parents=True, exist_ok=False)
            manifest = build(
                args.output.resolve(),
                args.cache.resolve(),
                args.source_archive,
                args.jobs,
                args.work_dir.resolve(),
            )
        else:
            with tempfile.TemporaryDirectory(prefix="cleantake-media-") as temporary:
                manifest = build(
                    args.output.resolve(),
                    args.cache.resolve(),
                    args.source_archive,
                    args.jobs,
                    Path(temporary).resolve(),
                )
        print(
            json.dumps(
                {
                    "target": manifest["target"],
                    "ffmpeg_version": manifest["ffmpeg_version"],
                    "status": "verified",
                    "output": str(args.output.resolve()),
                }
            )
        )
        return 0
    except (BuildError, OSError) as error:
        print(f"Media build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
