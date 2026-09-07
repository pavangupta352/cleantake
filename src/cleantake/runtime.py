"""Runtime locations shared by source installations and native distributions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class RuntimeDependencyError(ValueError):
    """A required media component is missing or cannot be executed."""


def default_workspace() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CleanTake"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CleanTake"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "cleantake"


def subprocess_options() -> dict:
    """Keep media helpers invisible while leaving their pipes available."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def media_binary(name: str) -> str:
    if name not in {"ffmpeg", "ffprobe"}:
        raise ValueError("Unknown media component")
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS).resolve()
        candidate = root / "media" / (name + (".exe" if sys.platform == "win32" else ""))
        resolved = candidate.resolve()
        if (
            not resolved.is_relative_to(root)
            or not resolved.is_file()
            or resolved.stat().st_size == 0
            or not os.access(resolved, os.X_OK)
        ):
            raise RuntimeDependencyError(
                f"Bundled {name} is missing or damaged; reinstall CleanTake."
            )
        return str(resolved)
    candidate = shutil.which(name)
    if candidate is None:
        raise RuntimeDependencyError(f"{name} is required; install FFmpeg and add it to PATH.")
    return str(Path(candidate).resolve())


def check_media_tools() -> dict:
    """Execute each selected component so a corrupt installation fails early."""
    result = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            path = media_binary(name)
            completed = subprocess.run(
                [path, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                **subprocess_options(),
            )
            if completed.returncode:
                raise RuntimeDependencyError(f"Cannot run {name}; reinstall CleanTake or FFmpeg.")
            result[name] = {"available": True, "action": None}
        except (RuntimeDependencyError, OSError, subprocess.TimeoutExpired) as error:
            action = (
                str(error)
                if isinstance(error, RuntimeDependencyError)
                else (f"Cannot run {name}; reinstall CleanTake or FFmpeg.")
            )
            result[name] = {"available": False, "action": action}
    return result
