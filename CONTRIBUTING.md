# Contributing to CleanTake

CleanTake recovers damaged passages from alternate recordings and keeps every repair editable and traceable to its source.

Start with the [architecture](docs/ARCHITECTURE.md), [roadmap](docs/ROADMAP.md) and [validation contract](docs/VALIDATION.md). The supported workflow matters more than adding controls or another processing model.

## Development environment

Install Python 3.12 or later, [uv](https://docs.astral.sh/uv/), and [FFmpeg](https://ffmpeg.org/download.html). The studio additionally uses Node.js 22.12 or later.

```sh
git clone https://github.com/pavangupta352/cleantake.git
cd cleantake
uv sync --locked
uv run pytest
uv run ruff check src tests scripts
```

For studio changes:

```sh
cd studio
npm ci
npx playwright install chromium firefox webkit
npm run build
npm run test:e2e
```

The browser tests use their own temporary workspace and a real local API. Ports
5173 and 8765 must be available; the runner refuses to reuse an existing server.
From the repository root, `uv run python scripts/build_release.py` refreshes the
bundled studio and its notices before building the wheel and source archive.

Audio integration tests exercise the installed FFmpeg. If a dependency is missing, record the skipped checks; do not report a complete verification run.

## Useful contributions

- Reproducible alignment failures, including independent clock drift and partial overlap.
- Incorrect damage suggestions on real shared silence, breaths, laughter or overlapping speakers.
- Distracting joins with the original, alternate and accepted repair available for comparison.
- Installation failures, inaccessible controls and missing recovery paths.
- Small, well-tested improvements to source provenance and portable exports.

## Changes and tests

Keep changes focused and explain the user-visible behavior. For a bug, add a test that reproduces the failure before changing the implementation. Expected timestamps and samples must be derived independently of the function being tested. Use real decoding and output checks when working on media boundaries.

The original performance is the source of truth. Preserve input files, their identifiers and timing transforms. A change that shortens the recording, silently substitutes uncertain sources or discards a speaker needs to be treated as a correctness defect.

Run the relevant tests and lint before submitting. State exactly what was tested, on which platform, and which cases remain untested. Keep dependency changes intentional and update the lock file.

## Audio fixtures

Do not attach private recordings or conversations to public issues. Use a short synthetic numeric fixture or a recording you have permission to share. Include the recording's license, source URL or permission, exact excerpt bounds and modifications. Injected damage must be described as injected.

For source-swapping defects, include each relevant source and the project decision list when possible. A final mixed file alone rarely explains where an alignment or transition failed.

## Pull requests

Describe the problem, the behavior after the change and the validation. Screenshots help with interface changes; short level-matched audio comparisons help with audible changes. Do not include private local paths, access tokens, unrelated generated files or media without redistribution rights.
