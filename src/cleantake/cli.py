"""Command-line entry point for local dialogue recovery."""

from __future__ import annotations

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

import functools
import json
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from cleantake import __version__
from cleantake.exports import ExportError, export_project
from cleantake.media import MediaError, inspect_media
from cleantake.portability import export_archive, import_archive
from cleantake.projects import ProjectError, ProjectStore
from cleantake.runtime import check_media_tools, default_workspace

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Recover damaged dialogue from simultaneous recordings.",
)


def _json(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))


def _guard(function):
    @functools.wraps(function)
    def checked(*args, **kwargs):
        lease = None
        try:
            ctx = kwargs.get("ctx")
            if ctx is not None and function.__name__ != "studio":
                from cleantake.server.jobs import WorkspaceLease

                ctx.obj.mkdir(parents=True, exist_ok=True)
                lease = WorkspaceLease(ctx.obj)
            return function(*args, **kwargs)
        except (
            ProjectError,
            MediaError,
            ExportError,
            ValidationError,
            ValueError,
            OverflowError,
            OSError,
        ) as error:
            typer.echo(f"CleanTake: {error}", err=True)
            raise typer.Exit(1) from error
        finally:
            if lease is not None:
                lease.close()

    return checked


def _store(ctx) -> ProjectStore:
    return ProjectStore(ctx.obj / "projects")


def _version(value: bool):
    if value:
        typer.echo(f"CleanTake {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[
        Path | None, typer.Option(help="Local project and export workspace.")
    ] = None,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,
):
    ctx.obj = workspace or default_workspace()


@app.command()
def doctor():
    """Check the local media tools and packaged studio."""
    result = {"version": __version__}
    result.update(check_media_tools())
    ready = all(result[name]["available"] for name in ("ffmpeg", "ffprobe"))
    result["studio"] = {"available": (Path(__file__).parent / "static/index.html").is_file()}
    _json(result)
    if not ready:
        raise typer.Exit(1)


@app.command()
@_guard
def demo(ctx: typer.Context):
    """Create an offline sample project with a labeled half-second dropout."""
    from cleantake.demo import create_demo

    _json(create_demo(_store(ctx)))


@app.command()
@_guard
def create(ctx: typer.Context, name: str):
    """Create a saved project."""
    store = _store(ctx)
    _json(store.get_public(store.create(name).id))


@app.command("list")
@_guard
def list_projects(ctx: typer.Context):
    """List saved projects."""
    _json({"projects": [project.model_dump(mode="json") for project in _store(ctx).list()]})


@app.command()
@_guard
def show(ctx: typer.Context, project_id: str):
    """Show a project's sources and repair decisions."""
    _json(_store(ctx).get_public(project_id))


def _import(store, project_id, file, *, name=None, channel=None, stream=0):
    if file.stat().st_size > 8 * 1024**3:
        raise MediaError("Recording exceeds the 8 GiB import limit")
    probe = inspect_media(file)
    if stream < 0 or stream >= len(probe.audio_streams):
        raise MediaError("Selected audio stream does not exist")
    if probe.audio_streams[stream].duration_seconds > 14_400:
        raise MediaError("Recording exceeds the four-hour duration limit")
    return store.import_source(project_id, file, name=name, channel=channel, stream=stream)


@app.command("import")
@_guard
def import_source(
    ctx: typer.Context,
    project_id: str,
    file: Path,
    name: str | None = None,
    channel: int | None = None,
    stream: int = 0,
):
    """Copy a recording into a project; optionally select an audio channel."""
    store = _store(ctx)
    _import(store, project_id, file, name=name, channel=channel, stream=stream)
    _json(store.get_public(project_id))


@app.command()
@_guard
def analyze(ctx: typer.Context, project_id: str):
    """Align alternate recordings and propose reviewable repairs."""
    store = _store(ctx)
    store.analyze(project_id)
    _json(store.get_public(project_id))


@app.command("export")
@_guard
def export(
    ctx: typer.Context,
    project_id: str,
    output: Annotated[Path, typer.Option(help="New directory for all exported artifacts.")],
    format: str = "wav",
    finish: bool = False,
):
    """Export accepted edits, aligned stems, source map and editable session."""
    _json(export_project(_store(ctx), project_id, output, format=format, finish=finish))


@app.command("source")
@_guard
def source_settings(
    ctx: typer.Context,
    project_id: str,
    source_id: str,
    name: str | None = None,
    speaker: str | None = None,
    offset: float | None = None,
    drift: float | None = None,
    polarity: int | None = None,
):
    """Rename a source or set its manual offset in seconds and drift in ppm."""
    changes = {
        key: value for key, value in {"name": name, "speaker": speaker}.items() if value is not None
    }
    alignment = {
        key: value
        for key, value in {
            "offset_seconds": offset,
            "drift_ppm": drift,
            "polarity": polarity,
        }.items()
        if value is not None
    }
    if alignment:
        changes["alignment"] = alignment
    if not changes:
        raise ValueError("Provide a source setting to change")
    store = _store(ctx)
    store.update_source(project_id, source_id, changes)
    _json(store.get_public(project_id))


@app.command("add-repair")
@_guard
def add_repair(
    ctx: typer.Context,
    project_id: str,
    source_id: str,
    start: Annotated[float, typer.Option(min=0, help="Start in project seconds.")],
    end: Annotated[float, typer.Option(min=0, help="End in project seconds.")],
    gain: float = 0,
    fade: float = 12,
):
    """Propose a manual repair with gain in dB and crossfade in milliseconds."""
    store = _store(ctx)
    rate = store.get(project_id).sample_rate
    store.add_repair(
        project_id,
        start_frame=round(start * rate),
        end_frame=round(end * rate),
        kind="manual",
        source_id=source_id,
        confidence=1,
        reason="Manual source selection",
        gain_db=gain,
        fade_ms=fade,
    )
    _json(store.get_public(project_id))


@app.command()
@_guard
def edit(
    ctx: typer.Context,
    project_id: str,
    repair_id: str,
    status: str | None = None,
    source: str | None = None,
    gain: float | None = None,
    fade: float | None = None,
    start: float | None = None,
    end: float | None = None,
):
    """Revise or accept a saved repair; start and end use project seconds."""
    store = _store(ctx)
    rate = store.get(project_id).sample_rate
    changes = {
        key: value
        for key, value in {
            "status": status,
            "source_id": source,
            "gain_db": gain,
            "fade_ms": fade,
            "start_frame": None if start is None else round(start * rate),
            "end_frame": None if end is None else round(end * rate),
        }.items()
        if value is not None
    }
    if not changes:
        raise ValueError("Provide a repair setting to change")
    store.update_repair(project_id, repair_id, changes)
    _json(store.get_public(project_id))


@app.command()
@_guard
def undo(ctx: typer.Context, project_id: str):
    """Undo the most recent saved change."""
    store = _store(ctx)
    store.undo(project_id)
    _json(store.get_public(project_id))


@app.command()
@_guard
def redo(ctx: typer.Context, project_id: str):
    """Restore the most recently undone change."""
    store = _store(ctx)
    store.redo(project_id)
    _json(store.get_public(project_id))


@app.command()
@_guard
def repair(
    ctx: typer.Context,
    main: Path,
    backups: Annotated[list[Path], typer.Argument(help="One to three simultaneous backups.")],
    output: Annotated[Path, typer.Option(help="New export directory; never overwritten.")],
    accept_confident: Annotated[
        bool, typer.Option(help="Explicitly accept suggestions meeting the chosen evidence score.")
    ] = False,
    min_confidence: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.9,
    format: str = "wav",
    finish: bool = False,
):
    """Create a reusable project, analyze sources and export its accepted repairs."""
    if not 1 <= len(backups) <= 3:
        raise ValueError("Provide one to three alternate recordings")
    if output.exists() or output.is_symlink():
        raise ExportError("Export destination already exists")
    store = _store(ctx)
    project = store.create(main.stem)
    try:
        for path in [main, *backups]:
            _import(store, project.id, path)
        project = store.analyze(project.id)
        if accept_confident:
            for proposed in project.repairs:
                if (
                    proposed.status == "proposed"
                    and proposed.source_id is not None
                    and proposed.confidence >= min_confidence
                ):
                    store.update_repair(project.id, proposed.id, {"status": "accepted"})
        project = store.get(project.id)
        result = export_project(store, project.id, output, format=format, finish=finish)
    except Exception:
        typer.echo(f"Project retained for review: {project.id}", err=True)
        raise
    result.update(
        project_id=project.id,
        accepted=sum(r.status == "accepted" for r in project.repairs),
        pending=sum(r.status == "proposed" for r in project.repairs),
        unresolved=sum(r.status == "unresolved" for r in project.repairs),
        automatic_acceptance=accept_confident,
    )
    _json(result)


@app.command()
@_guard
def archive(ctx: typer.Context, project_id: str, output: Annotated[Path, typer.Option()]):
    """Save a portable archive including the original recordings."""
    _json(export_archive(_store(ctx), project_id, output))


@app.command("open-archive")
@_guard
def open_archive(ctx: typer.Context, file: Path):
    """Import a verified portable archive as a new project."""
    store = _store(ctx)
    project = import_archive(store, file)
    _json(store.get_public(project.id))


@app.command()
@_guard
def studio(
    ctx: typer.Context,
    workspace: Path | None = None,
    port: Annotated[int, typer.Option(min=0, max=65535)] = 0,
    no_browser: bool = False,
    print_link: Annotated[
        bool, typer.Option(help="Explicitly print the private session URL to this terminal.")
    ] = False,
):
    """Open the local editing studio on this computer's loopback interface."""
    import uvicorn

    from cleantake.server import create_app

    application = create_app(workspace or ctx.obj)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        actual_port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{actual_port}/"
        launch = f"{base}#token={application.state.token}"
        typer.echo(f"CleanTake studio: {base}")
        if print_link:
            typer.echo(launch)
        if not no_browser:
            opener = threading.Timer(0.8, lambda: webbrowser.open(launch))
            opener.daemon = True
            opener.start()
        elif not print_link:
            typer.echo("Use --print-link to display the private access link in this terminal.")
        configuration = uvicorn.Config(
            application, host="127.0.0.1", port=actual_port, access_log=False, log_level="warning"
        )
        uvicorn.Server(configuration).run(sockets=[listener])


if __name__ == "__main__":
    app()
