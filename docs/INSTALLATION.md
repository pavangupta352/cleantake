# Installation

For the desktop app, use the [Mac, Windows or Linux installer](DESKTOP.md).
It includes the application runtimes, audio tools and offline sample.

## Command-line and browser edition

The following instructions install the optional Python package. It needs Python
3.12 or newer and FFmpeg with FFprobe on your `PATH`. This package includes the
browser studio and licensed sample recordings. Node.js is needed only to change
or rebuild the UI. Its workspace and exports are compatible with the desktop app.

## Install the media tools

| System | Install FFmpeg |
|---|---|
| macOS with Homebrew | `brew install ffmpeg` |
| Ubuntu / Debian | `sudo apt-get update && sudo apt-get install ffmpeg` |
| Windows with Chocolatey | `choco install ffmpeg --yes` |

Other FFmpeg installations work if both `ffmpeg` and `ffprobe` are available in a
new terminal. See the [official FFmpeg download page](https://ffmpeg.org/download.html)
for alternatives.

## Install CleanTake

Download the wheel from [Releases](https://github.com/pavangupta352/cleantake/releases).
With [uv](https://docs.astral.sh/uv/getting-started/installation/), install the
downloaded file in its own environment:

```sh
uv tool install --python 3.12 ./cleantake-0.2.0-py3-none-any.whl
cleantake doctor
cleantake studio
```

If your shell cannot find `cleantake`, run `uv tool update-shell` and open a new
terminal. Standard pip in a virtual environment also works:

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install ./cleantake-0.2.0-py3-none-any.whl
cleantake doctor
```

The wheel is platform independent; NumPy, SciPy and other dependencies still
need wheels compatible with your Python and operating system. See the actual
[check results](https://github.com/pavangupta352/cleantake/actions/workflows/ci.yml)
for tested systems. An unsupported architecture may require additional native
build tools.

## Your workspace

CleanTake copies imported recordings into its workspace. Originals and decoded
caches are immutable; decisions are stored separately. Default locations are:

| System | Location |
|---|---|
| macOS | `~/Library/Application Support/CleanTake` |
| Windows | `%LOCALAPPDATA%\CleanTake` |
| Linux | `$XDG_DATA_HOME/cleantake`, or `~/.local/share/cleantake` |

Choose another location with `cleantake --workspace /path/to/work studio`.
Close the studio before using CLI commands against that workspace. A workspace
lock prevents two processes from making conflicting changes.

Allow disk space for the copied original, a 48 kHz mono float cache (about
691 MB per hour per source), exported stems and any portable archives. Imports
are limited to four sources, 8 GiB per uploaded recording and four hours per
recording. These are input limits, not a processing-time or memory guarantee.

## Local access

`cleantake studio` opens a private session in your default browser on
`127.0.0.1`, using an available port. Keep the terminal open while editing.
The access token is in the launch URL fragment and is removed from the address
bar after the studio reads it. The application does not upload your recordings
or use an external processing service.

For a different local browser, use `cleantake studio --no-browser --print-link`
and open the printed private link on this computer. Do not share that link or
expose the port through a public proxy. See [security](../SECURITY.md).

## Build from source

```sh
git clone https://github.com/pavangupta352/cleantake.git
cd cleantake
uv sync --locked
uv run cleantake doctor
uv run cleantake studio
```

Committed browser assets make the source installation usable without Node.js.
After editing the studio, rebuild those assets and distributions with:

```sh
uv run python scripts/build_release.py
```

The build uses `npm ci`, the locked studio dependencies, full bundled license
notices, and `uv build`. Outputs and checksums are in `dist/`.

## Common problems

- **FFmpeg missing in the CLI/browser edition:** install both media tools, reopen
  the terminal, then run `cleantake doctor` again. The desktop app carries its own
  copies; reinstall its matching package if bundled files are missing.
- **Workspace already open:** stop its studio process before running CLI edits
  or starting a second studio. Do not delete the lock to bypass an active process.
- **Recording will not import:** use a self-contained audio/video file. Playlists
  and files that refer to other local or remote media are rejected. Select the
  desired audio stream or channel in the import options when needed.
- **No alignment or suggestion:** verify the recordings contain the same event.
  Use a shared transient and manual alignment when automatic evidence is weak;
  then audition and create a manual repair. See [the guide](GUIDE.md).
- **Interrupted job:** reopen the studio. Interrupted work is labeled as such;
  the previous published project revision remains available. Retry the operation
  after checking free disk space and source integrity.
