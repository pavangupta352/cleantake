#!/usr/bin/env python3
"""Audit native payloads and exercise real installers on disposable CI runners.

A restricted application PATH is one check, not a clean-machine claim. Dependency
reports name the OS libraries used on the observed runner. This helper never
changes sandbox policy, removes quarantine, or deletes a user's application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import selectors
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ARCHES = {
    62: "x64",
    183: "arm64",
    0x8664: "x64",
    0xAA64: "arm64",
    0x14C: "x86",
    0x01000007: "x64",
    0x0100000C: "arm64",
}
RUNTIME_LIB = re.compile(
    r"^(?:lib)?(?:python|avcodec|avformat|avutil|swresample|swscale|"
    r"openblas|scipy|numpy|sndfile|gfortran|quadmath)",
    re.I,
)


def redact(value: str) -> str:
    return re.sub(r"(?i)([#?&]token=)[^\s\"'<>]+", r"\1[redacted]", value)


def run(command, *, check=True, env=None, cwd=None, timeout=180):
    result = subprocess.run(
        [str(item) for item in command],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        env=env,
        cwd=cwd,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"{Path(command[0]).name} failed ({result.returncode}): "
            f"{redact((result.stdout + result.stderr)[-12000:])}"
        )
    return result


def binary_architectures(data: bytes) -> set[str]:
    try:
        if data.startswith(b"\x7fELF"):
            if len(data) < 64:
                raise ValueError("truncated ELF header")
            endian = "<" if data[5] == 1 else ">"
            return {ARCHES.get(struct.unpack_from(endian + "H", data, 18)[0], "unsupported")}
        if data.startswith(b"MZ"):
            offset = struct.unpack_from("<I", data, 60)[0]
            if data[offset : offset + 4] != b"PE\0\0":
                raise ValueError("invalid PE signature")
            return {ARCHES.get(struct.unpack_from("<H", data, offset + 4)[0], "unsupported")}
        if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
            endian = "<" if data[0] == 0xCF else ">"
            return {ARCHES.get(struct.unpack_from(endian + "I", data, 4)[0], "unsupported")}
        if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
            count = struct.unpack_from(">I", data, 4)[0]
            stride = 24 if data[3] == 0xBF else 20
            if count > 32 or len(data) < 8 + stride * count:
                raise ValueError("truncated or invalid universal Mach-O header")
            return {
                ARCHES.get(struct.unpack_from(">I", data, 8 + stride * i)[0], "unsupported")
                for i in range(count)
            }
    except struct.error as exc:
        raise ValueError("truncated native binary header") from exc
    return set()


def dependency_origin(path: Path, root: Path, system: str) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(root.resolve()):
        return "bundled"
    if RUNTIME_LIB.match(resolved.name):
        raise ValueError(f"external application runtime: {path}")
    allowed = {
        "Darwin": (
            "/usr/lib/",
            "/System/Library/",
            "/System/Volumes/Preboot/Cryptexes/OS/System/Library/",
            "/System/Volumes/Preboot/Cryptexes/OS/usr/lib/",
        ),
        "Linux": ("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/"),
    }
    if system == "Windows":
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
        if resolved.is_relative_to(windows / "System32"):
            return "os"
    elif any(str(resolved).startswith(prefix) for prefix in allowed[system]):
        return "os"
    raise ValueError(f"dependency outside the application and approved OS locations: {path}")


def workspace_hashes(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def require_retained(workspace: Path, before: dict[str, str]) -> None:
    after = workspace_hashes(workspace)
    missing = sorted(before.keys() - after.keys())
    changed = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
    if missing or changed:
        raise ValueError(f"saved workspace was not retained: missing={missing}, changed={changed}")


def extract_portable(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:*") as source:
        source.extractall(destination, filter="data")


def artifact(directory: Path, arch: str, suffix: str) -> Path:
    artifact_arch = "amd64" if suffix == ".deb" and arch == "x64" else arch
    matches = sorted(directory.glob(f"CleanTake-*-{artifact_arch}{suffix}"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {arch}{suffix} artifact, found {len(matches)}")
    return matches[0].resolve()


def elf_dependency_paths(output: str) -> list[Path]:
    paths = []
    for line in output.splitlines():
        match = re.fullmatch(r"\s*(?:.+?\s+=>\s+)?(/.*?)\s+\(0x[0-9a-fA-F]+\)\s*", line)
        if match:
            paths.append(Path(match.group(1)))
    return paths


def pe_imports(data: bytes) -> set[str]:
    """Read regular and delay-load PE imports, without a compiler on PATH."""
    pe = struct.unpack_from("<I", data, 60)[0]
    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic != 0x20B:
        raise ValueError("expected a 64-bit PE image")
    image_base = struct.unpack_from("<Q", data, optional + 24)[0]
    section_table = optional + optional_size
    ranges = []
    for index in range(sections):
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, section_table + 40 * index + 8
        )
        ranges.append((virtual_address, virtual_address + max(virtual_size, raw_size), raw_offset))

    def offset(rva):
        for start, end, raw in ranges:
            if start <= rva < end:
                return raw + rva - start
        raise ValueError(f"invalid PE import address {rva}")

    names = set()
    for directory_index, stride, name_position in ((1, 20, 12), (13, 32, 4)):
        rva, size = struct.unpack_from("<II", data, optional + 112 + directory_index * 8)
        if not rva or not size:
            continue
        start = offset(rva)
        for index in range(min(size // stride + 1, 10000)):
            descriptor = data[start + index * stride : start + (index + 1) * stride]
            if len(descriptor) != stride:
                raise ValueError("truncated PE import descriptor")
            if not any(descriptor):
                break
            name_rva = struct.unpack_from("<I", descriptor, name_position)[0]
            if directory_index == 13 and not struct.unpack_from("<I", descriptor)[0] & 1:
                name_rva -= image_base
            position = offset(name_rva)
            end = data.find(b"\0", position, position + 512)
            if end < 0:
                raise ValueError("invalid PE import name")
            names.add(data[position:end].decode("ascii"))
    return names


def mac_dependencies(binary: Path, root: Path, binaries: list[Path]) -> list[dict]:
    # otool interprets a trailing '(GPU)' as an archive-member selector. Inspect
    # through a plain alias while resolving loader paths against the real file.
    with tempfile.TemporaryDirectory(prefix="cleantake-inspect-") as temporary:
        alias = Path(temporary) / "binary"
        alias.symlink_to(binary.resolve())
        listing = run(["otool", "-L", alias]).stdout.splitlines()[1:]
        loads = run(["otool", "-l", alias]).stdout
    rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", loads)
    self_names = set(re.findall(r"cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.*?) \(offset", loads))
    executable_dirs = [binary.parent] + [
        item.parent
        for item in binaries
        if item.parent.name == "MacOS" or item.name == "cleantake-runtime"
    ]
    result = []
    for line in listing:
        if not line[:1].isspace():
            continue
        name = line.strip().split(" (compatibility version", 1)[0]
        if not name or name in self_names:
            continue
        if name.startswith("/"):
            origin = dependency_origin(Path(name), root, "Darwin")
            if origin == "bundled" and not Path(name).exists():
                raise ValueError(f"missing bundled dependency {name}")
            result.append({"name": name, "origin": origin})
            continue
        candidates = []
        if name.startswith("@loader_path/"):
            candidates.append(binary.parent / name.removeprefix("@loader_path/"))
        elif name.startswith("@executable_path/"):
            candidates.extend(
                directory / name.removeprefix("@executable_path/") for directory in executable_dirs
            )
        elif name.startswith("@rpath/"):
            suffix = name.removeprefix("@rpath/")
            for rpath in rpaths:
                for directory in executable_dirs:
                    expanded = rpath.replace("@loader_path", str(binary.parent)).replace(
                        "@executable_path", str(directory)
                    )
                    candidates.append(Path(expanded) / suffix)
            # dyld can inherit run paths from the executable and parent frameworks.
            candidates.extend(item for item in binaries if item.as_posix().endswith("/" + suffix))
        match = next((path for path in candidates if path.exists()), None)
        if match is None:
            raise ValueError(f"unresolved Mach-O dependency {name} in {binary.relative_to(root)}")
        origin = dependency_origin(match, root, "Darwin")
        result.append(
            {
                "name": name,
                "origin": origin,
                "resolved": str(match.resolve().relative_to(root.resolve()))
                if origin == "bundled"
                else str(match.resolve()),
            }
        )
    return result


def audit(root: Path, arch: str) -> dict:
    root = root.resolve()
    system = platform.system()
    binaries = []
    installer_helpers = []
    seen = set()
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"payload symlink escapes application: {candidate}")
        if resolved in seen:
            continue
        seen.add(resolved)
        with candidate.open("rb") as source:
            header = source.read(65536)
        arches = binary_architectures(header)
        if arches:
            if system == "Windows" and candidate.name == "Uninstall CleanTake.exe":
                installer_helpers.append(
                    {
                        "path": str(candidate.relative_to(root)),
                        "architectures": sorted(arches),
                        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                        "purpose": "NSIS removal launcher; separate from the application runtime",
                    }
                )
                continue
            if arch not in arches:
                raise ValueError(f"wrong architecture {arches} for {candidate.relative_to(root)}")
            binaries.append(candidate)
    if not binaries:
        raise ValueError("no native binaries found in installed application")
    dll_index = {item.name.lower(): item for item in binaries}
    library_dirs = sorted({str(item.parent) for item in binaries})
    loader_env = {
        key: value for key, value in os.environ.items() if not key.startswith(("LD_", "DYLD_"))
    }
    loader_env["LD_LIBRARY_PATH"] = os.pathsep.join(library_dirs)
    records = []
    for binary in binaries:
        dependencies = []
        versions = []
        if system == "Darwin":
            dependencies = mac_dependencies(binary, root, binaries)
        elif system == "Windows":
            for name in sorted(pe_imports(binary.read_bytes())):
                if name.lower().startswith(("api-ms-", "ext-ms-")):
                    dependencies.append({"name": name, "origin": "os-api-contract"})
                    continue
                resolved = dll_index.get(name.lower())
                if resolved is None:
                    resolved = Path(os.environ["SystemRoot"]) / "System32" / name
                if not resolved.exists():
                    raise ValueError(f"missing Windows dependency {name} of {binary.name}")
                dependencies.append(
                    {"name": name, "origin": dependency_origin(resolved, root, system)}
                )
        else:
            listing = run(["ldd", binary], check=False, env=loader_env)
            output = listing.stdout + listing.stderr
            if listing.returncode and not any(
                term in output for term in ("not a dynamic executable", "statically linked")
            ):
                raise ValueError(f"ldd could not inspect {binary.name}: {output[-2000:]}")
            for line in output.splitlines():
                if "not found" in line:
                    raise ValueError(f"missing ELF dependency of {binary.name}: {line.strip()}")
            for resolved in elf_dependency_paths(output):
                dependencies.append(
                    {
                        "name": resolved.name,
                        "origin": dependency_origin(resolved, root, system),
                        "resolved": str(resolved.relative_to(root))
                        if resolved.is_relative_to(root)
                        else str(resolved),
                    }
                )
            version_text = run(["readelf", "--version-info", binary], check=False).stdout
            versions = sorted(set(re.findall(r"\b(?:GLIBC|GLIBCXX|CXXABI)_[\d.]+", version_text)))
        records.append(
            {
                "path": str(binary.relative_to(root)),
                "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "dependencies": dependencies,
                "symbol_versions": versions,
            }
        )
    return {
        "system": system,
        "architecture": arch,
        "binary_count": len(records),
        "binaries": records,
        "installer_helpers": installer_helpers,
        "scope": "Static dependency inventory plus separate installed launch tests. "
        "Linux resolution includes bundled library directories; dyld inherited "
        "run paths are resolved against bundled native files. This is not a "
        "claim that the CI image lacks preinstalled development software.",
    }


def wait_for(predicate, message: str, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise RuntimeError(message)


def app_smoke(executable: Path, workspace: Path, evidence: Path, desktop: Path) -> dict:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm test controller is unavailable")
    env = os.environ.copy()
    env.update(
        CLEANTAKE_APP=str(executable),
        CLEANTAKE_TEST_WORKSPACE=str(workspace),
        CLEANTAKE_TEST_REPORT_DIR=str(evidence),
    )
    command = [npm, "run", "test:app"]
    if os.name == "nt":
        command = [os.environ["COMSPEC"], "/d", "/c", *command]
    result = run(command, env=env, cwd=desktop, timeout=900)
    return {
        "exit_code": result.returncode,
        "output": redact((result.stdout + result.stderr)[-16000:]),
    }


def portable_launch_diagnostic(executable: Path, directory: Path, seconds=10) -> dict:
    """Capture a failed portable launch without changing sandbox or trust policy."""
    import psutil

    if os.name != "posix" or not 2 <= seconds <= 10:
        raise ValueError("portable launch diagnostic requires POSIX and a 2–10 second bound")
    directory.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["PATH"] = ""
    for key in (
        "ELECTRON_RUN_AS_NODE", "NODE_OPTIONS", "PYTHONHOME", "PYTHONPATH",
        "VIRTUAL_ENV", "CONDA_PREFIX",
    ):
        env.pop(key, None)
    started = time.monotonic()
    process = psutil.Popen(
        [str(executable), f"--user-data-dir={directory / 'Preferences café'}",
         "--workspace", str(directory / "Workspace café")],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, start_new_session=True,
    )
    assert process.stderr is not None
    os.set_blocking(process.stderr.fileno(), False)
    captured = bytearray()
    observed = {process.pid: process}
    selector = selectors.DefaultSelector()
    selector.register(process.stderr, selectors.EVENT_READ)

    def inspect_children():
        try:
            observed.update({child.pid: child for child in process.children(recursive=True)})
        except psutil.NoSuchProcess:
            pass

    def drain():
        for key, _ in selector.select(timeout=0):
            block = os.read(key.fd, 65536)
            if block:
                captured.extend(block[: max(0, 12000 - len(captured))])
            else:
                selector.unregister(key.fileobj)

    timed_out = False
    try:
        while time.monotonic() - started < seconds - 1:
            inspect_children()
            drain()
            if process.poll() is not None:
                drain()
                break
            time.sleep(0.02)
        else:
            timed_out = True
    finally:
        inspect_children()
        # Include children reparented after a very early probe exit. The private
        # session's process group cannot contain an unrelated application.
        for candidate in psutil.process_iter():
            try:
                if os.getpgid(candidate.pid) == process.pid:
                    observed[candidate.pid] = candidate
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                pass
        for child in reversed(list(observed.values())):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(list(observed.values()), timeout=0.8)
        drain()
        selector.close()
        process.stderr.close()
    survivors = []
    for child in observed.values():
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                survivors.append(child.pid)
        except psutil.NoSuchProcess:
            pass
    return {
        "exit_code": process.poll(), "timed_out": timed_out,
        "elapsed_seconds": time.monotonic() - started,
        "stderr": redact(captured.decode("utf-8", errors="replace"))[:12000],
        "observed_processes": sorted(observed), "surviving_processes": survivors,
        "sandbox_bypass": False,
    }


def signature_status(executable: Path, required: bool) -> dict:
    if platform.system() == "Darwin":
        bundle = executable.parents[2]
        verify = run(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", bundle], check=False
        )
        display = run(["codesign", "--display", "--verbose=4", bundle], check=False)
        assess = run(["spctl", "--assess", "--type", "execute", "--verbose=4", bundle], check=False)
        status = (
            "ad-hoc"
            if "Signature=adhoc" in display.stderr
            else (
                "developer-id"
                if "Authority=Developer ID Application:" in display.stderr
                else "unsigned"
            )
        )
        if verify.returncode or (required and (status != "developer-id" or assess.returncode)):
            raise ValueError(
                f"macOS signature verification failed: {redact(verify.stderr + assess.stderr)}"
            )
        return {
            "status": status,
            "integrity_exit": verify.returncode,
            "gatekeeper_exit": assess.returncode,
            "details": redact(display.stderr + assess.stderr),
        }
    if platform.system() == "Windows":
        env = os.environ.copy()
        env["CLEANTAKE_SIGNATURE_TARGET"] = str(executable)
        result = run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$s=Get-AuthenticodeSignature -LiteralPath $env:CLEANTAKE_SIGNATURE_TARGET; "
                "@{status=[string]$s.Status; subject=[string]$s.SignerCertificate.Subject} "
                "| ConvertTo-Json -Compress",
            ],
            env=env,
        )
        details = json.loads(result.stdout)
        if required and details["status"] != "Valid":
            raise ValueError(f"Authenticode verification failed: {details}")
        return details
    return {"status": "unsigned-package", "note": "No Linux package signing key configured"}


def require_mountpoint(entities: list[dict], expected: Path):
    # hdiutil can return /private/var and decomposed Unicode for the same inode.
    for entity in entities:
        actual = entity.get("mount-point")
        if actual:
            try:
                if Path(actual).samefile(expected):
                    return
            except OSError:
                pass
    raise ValueError("DMG did not mount at the owned test location")


def install_smoke(args) -> dict:
    system = platform.system()
    if system in ("Windows", "Linux") and os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("system installer tests require a disposable GitHub Actions runner")
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_controller": sys.version,
        "commit": os.environ.get("GITHUB_SHA"),
        "runner_image": {
            key: os.environ.get(key)
            for key in ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH")
        },
        "signing_requested": args.signed,
        "checks": [],
        "limits": [
            "The verification host has build tools installed; app launch removes "
            "developer tools from PATH and static checks inventory native dependencies.",
            "Installer runs as the verification account; Windows UAC and macOS "
            "first-download quarantine prompts require separate trust evidence.",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="CleanTake CI café ") as temporary:
        temp = Path(temporary)
        workspace = temp / "Saved projects café"
        workspace.mkdir()
        (workspace / ".retention-check").write_text(
            "CleanTake saved projects stay here\n", encoding="utf-8"
        )
        installed = False
        mounted = False
        install_root = None
        executable = None
        mountpoint = temp / "Mounted image"
        installer = None

        def install():
            nonlocal installed, mounted, install_root, executable
            if system == "Darwin":
                mountpoint.mkdir(exist_ok=True)
                attached = run(
                    [
                        "hdiutil",
                        "attach",
                        "-readonly",
                        "-nobrowse",
                        "-plist",
                        "-mountpoint",
                        mountpoint,
                        installer,
                    ]
                )
                mounted = True
                entities = plistlib.loads(attached.stdout.encode())["system-entities"]
                require_mountpoint(entities, mountpoint)
                source = mountpoint / "CleanTake.app"
                if not source.is_dir():
                    raise ValueError("DMG does not contain CleanTake.app")
                install_root = temp / "Applications café" / "CleanTake.app"
                install_root.parent.mkdir(exist_ok=True)
                installed = True
                run(["ditto", source, install_root])
                run(["hdiutil", "detach", mountpoint])
                mounted = False
                executable = install_root / "Contents/MacOS/CleanTake"
            elif system == "Windows":
                install_root = Path(os.environ["LOCALAPPDATA"]) / "Programs/CleanTake"
                installed = True
                run([installer, "/S"], timeout=600)
                executable = install_root / "CleanTake.exe"
                wait_for(executable.exists, "NSIS did not create the expected per-user executable")
            else:
                installed = True
                run(["sudo", "apt-get", "install", "--yes", str(installer)], timeout=600)
                listing = run(["dpkg-query", "-L", "cleantake"]).stdout.splitlines()
                candidates = [
                    Path(path)
                    for path in listing
                    if path.endswith("/cleantake")
                    and path.startswith("/opt/")
                    and Path(path).is_file()
                ]
                if len(candidates) != 1:
                    raise ValueError("Debian package did not install exactly one /opt executable")
                executable = candidates[0]
                install_root = executable.parent
            if not executable.is_file():
                raise ValueError("installed executable missing")

        def uninstall():
            nonlocal installed
            if not installed:
                return
            if system == "Darwin":
                if install_root and install_root.exists():
                    shutil.rmtree(install_root)
            elif system == "Windows":
                uninstaller = install_root / "Uninstall CleanTake.exe"
                if not uninstaller.is_file():
                    raise ValueError(
                        "NSIS uninstaller missing; preserving installation for diagnosis"
                    )
                run([uninstaller, "/S"], timeout=300)
                wait_for(
                    lambda: not (install_root / "CleanTake.exe").exists(),
                    "NSIS uninstall did not remove the application executable",
                )
            else:
                run(["sudo", "apt-get", "remove", "--yes", "cleantake"], timeout=300)
                if executable and executable.exists():
                    raise ValueError("Debian uninstall retained the application executable")
            installed = False

        try:
            suffix = {"Darwin": ".dmg", "Windows": ".exe", "Linux": ".deb"}[system]
            installer = artifact(args.artifacts, args.arch, suffix)
            if (
                system == "Windows"
                and (Path(os.environ["LOCALAPPDATA"]) / "Programs/CleanTake").exists()
            ):
                raise ValueError("refusing to replace a preexisting CleanTake installation")
            if system == "Linux":
                existing = run(
                    ["dpkg-query", "-W", "-f=${db:Status-Status}", "cleantake"], check=False
                )
                if existing.returncode == 0 and existing.stdout.strip() == "installed":
                    raise ValueError("refusing to replace a preexisting CleanTake installation")
            install()
            report["installer"] = {
                "name": installer.name,
                "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
            }
            report["signature"] = signature_status(executable, args.signed)
            if system == "Windows":
                report["installer_signature"] = signature_status(installer, args.signed)
                report["uninstaller_signature"] = signature_status(
                    install_root / "Uninstall CleanTake.exe", args.signed
                )
            report["dependency_audit"] = audit(install_root, args.arch)
            report["checks"].append(
                {
                    "name": "installed-desktop",
                    **app_smoke(
                        executable, workspace, evidence / "installed-app", args.desktop.resolve()
                    ),
                }
            )
            before = workspace_hashes(workspace)
            if len(before) < 2:
                raise ValueError("desktop smoke produced no saved workspace files")
            uninstall()
            require_retained(workspace, before)
            report["checks"].append({"name": "uninstall-retains-projects", "files": len(before)})
            install()
            require_retained(workspace, before)
            report["checks"].append({"name": "reinstall-retains-projects", "files": len(before)})
            uninstall()
            require_retained(workspace, before)
            if system == "Linux":
                archive = artifact(args.artifacts, args.arch, ".tar.xz")
                report["portable"] = {
                    "name": archive.name,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }
                portable = temp / "Portable café"
                extract_portable(archive, portable)
                candidates = [path for path in portable.rglob("cleantake") if path.is_file()]
                if len(candidates) != 1:
                    raise ValueError(
                        "portable archive does not have exactly one application executable"
                    )
                report["portable_dependency_audit"] = audit(candidates[0].parent, args.arch)
                try:
                    portable_result = app_smoke(
                        candidates[0], temp / "Portable workspace café",
                        evidence / "portable-app", args.desktop.resolve(),
                    )
                except Exception:
                    try:
                        report["portable_launch_diagnostic"] = portable_launch_diagnostic(
                            candidates[0], temp / "Portable diagnostic café"
                        )
                    except Exception as diagnostic_error:
                        report["portable_launch_diagnostic"] = {
                            "error": redact(str(diagnostic_error))
                        }
                    journal = shutil.which("journalctl")
                    if journal:
                        try:
                            kernel = run(
                                [journal, "--kernel", "--since=-2min", "--no-pager", "-n", "80"],
                                check=False, timeout=3,
                            )
                            report["portable_kernel_diagnostic"] = {
                                "exit_code": kernel.returncode,
                                "denials": redact("\n".join(
                                    line for line in kernel.stdout.splitlines()
                                    if "cleantake" in line.lower() and "denied" in line.lower()
                                ))[:12000],
                                "stderr": redact(kernel.stderr)[:2000],
                            }
                        except Exception as journal_error:
                            report["portable_kernel_diagnostic"] = {
                                "error": redact(str(journal_error))
                            }
                    raise
                report["checks"].append(
                    {
                        "name": "portable-desktop",
                        **portable_result,
                    }
                )
            report["success"] = True
        except Exception as exc:
            report["success"] = False
            report["error"] = redact(str(exc))
            raise
        finally:
            try:
                if mounted:
                    run(["hdiutil", "detach", mountpoint])
                uninstall()
            except Exception as exc:
                report["cleanup_error"] = redact(str(exc))
                report["success"] = False
            (evidence / "install.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
    if not report["success"]:
        raise RuntimeError("native installer verification failed; inspect install.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    install_parser = subcommands.add_parser("install-smoke")
    install_parser.add_argument("--artifacts", type=Path, default=Path("dist/native"))
    install_parser.add_argument("--desktop", type=Path, default=Path("desktop"))
    install_parser.add_argument("--evidence", type=Path, default=Path("build/native/evidence"))
    install_parser.add_argument("--signed", action="store_true")
    audit_parser = subcommands.add_parser("audit")
    audit_parser.add_argument("--root", type=Path, required=True)
    audit_parser.add_argument("--report", type=Path, required=True)
    for child in (install_parser, audit_parser):
        child.add_argument("--arch", choices=("x64", "arm64"), required=True)
    args = parser.parse_args()
    if args.command == "audit":
        report = audit(args.root, args.arch)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        report = install_smoke(args)
    print(json.dumps({"success": report.get("success", True), "command": args.command}))


if __name__ == "__main__":
    main()
