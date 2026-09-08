"""Private desktop-parent protocol and first-run initialization."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

import uvicorn

from cleantake import __version__
from cleantake.demo import create_demo
from cleantake.projects import ProjectConflictError, ProjectStore
from cleantake.runtime import check_media_tools, default_workspace, isolated_child_stdin
from cleantake.server import create_app
from cleantake.server.jobs import atomic_json


class DesktopStartupError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise DesktopStartupError(
            "invalid_arguments", "Use --desktop with an optional --workspace folder."
        )


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=True, allow_nan=False), flush=True)


def initialize_workspace(application) -> None:
    """Publish the first sample and marker while create_app holds the lease."""
    workspace = application.state.workspace
    marker = workspace / ".desktop-initialized.json"
    if marker.is_symlink() or marker.with_suffix(".tmp").is_symlink():
        raise DesktopStartupError(
            "workspace_unavailable", "The workspace initialization marker is invalid."
        )
    if marker.exists():
        return
    stage = workspace / ".desktop-initializing"
    if stage.is_symlink():
        raise DesktopStartupError(
            "workspace_unavailable", "The workspace initialization folder is invalid."
        )
    if stage.exists():
        shutil.rmtree(stage)
    sample = None
    if not application.state.store.list():
        try:
            staged = ProjectStore(stage / "projects")
            sample = create_demo(staged)
            identifier = sample["project_id"]
            os.rename(staged.root / identifier, application.state.store.root / identifier)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    atomic_json(
        marker, {"version": 1, "sample_project_id": sample["project_id"] if sample else None}
    )


def run(workspace: Path) -> int:
    application = None
    listener = None
    server = None
    stopping = threading.Event()
    child_input = ExitStack()

    def control():
        try:
            while True:
                line = sys.stdin.readline(1024)
                if not line or line == "shutdown\n":
                    break
        except (OSError, ValueError):
            pass
        stopping.set()
        if server is not None:
            server.should_exit = True

    try:
        child_input.enter_context(isolated_child_stdin())
        tools = check_media_tools()
        if any(not tool["available"] for tool in tools.values()):
            raise DesktopStartupError(
                "media_tools_unavailable", "The audio tools cannot run. Reinstall CleanTake."
            )
        if not (Path(__file__).parent / "static/index.html").is_file():
            raise DesktopStartupError(
                "studio_unavailable", "The editing interface is missing. Reinstall CleanTake."
            )
        application = create_app(workspace)
        threading.Thread(target=control, name="cleantake-desktop-control", daemon=True).start()
        initialize_workspace(application)
        if stopping.is_set():
            return 0
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]

        class DesktopServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if stopping.is_set():
                    self.should_exit = True
                elif self.started and not self.should_exit:
                    _emit(
                        {
                            "event": "ready",
                            "version": __version__,
                            "url": f"http://127.0.0.1:{port}/#token={application.state.token}",
                        }
                    )

        server = DesktopServer(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="error",
                loop="asyncio",
                http="h11",
                ws="none",
                lifespan="on",
                timeout_graceful_shutdown=5,
            )
        )
        server.run(sockets=[listener])
        return 0
    except ProjectConflictError:
        _emit(
            {
                "event": "error",
                "code": "workspace_in_use",
                "message": "This workspace is already open. Close the other CleanTake window "
                "and try again.",
            }
        )
        return 1
    except DesktopStartupError as error:
        _emit({"event": "error", "code": error.code, "message": str(error)[:512]})
        return 1
    except (Exception, SystemExit):
        _emit(
            {
                "event": "error",
                "code": "startup_failed",
                "message": "CleanTake could not open its workspace. Check available disk space "
                "and folder permissions, then try again.",
            }
        )
        return 1
    finally:
        try:
            if application is not None:
                application.state.jobs.close()
            if listener is not None:
                listener.close()
        finally:
            child_input.close()


def main(arguments=None) -> int:
    parser = _Arguments(add_help=False)
    parser.add_argument("--desktop", action="store_true", required=True)
    parser.add_argument("--workspace", type=Path, default=None)
    try:
        options = parser.parse_args(arguments)
    except DesktopStartupError as error:
        _emit({"event": "error", "code": error.code, "message": str(error)})
        return 1
    return run(options.workspace or default_workspace())
