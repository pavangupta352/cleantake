# Desktop builds

The desktop shell opens the bundled studio and owns its local audio service.
Python, processing libraries, media tools, sample recordings, and the browser
runtime ship with the application. End users do not install these separately.

Version 0.2.0 is undergoing native release checks. See the
[distribution specification](../docs/NATIVE-DISTRIBUTION.md) for the acceptance
gates and [desktop guide](../docs/DESKTOP.md) for the installation experience.

## Build on the target system

Use the same operating system and architecture as the intended application.
The [native workflow](../.github/workflows/native.yml) lists the six supported
build environments and their toolchain packages. Cross-packaging an application
does not convert its Python service or media executables to another platform.

The pinned build uses uv 0.11.11 with its Python 3.12.13 build, Node.js 24,
the desktop lockfile, and the source verification tools described in
[the media build instructions](../packaging/ffmpeg/README.md). Run these from
the repository root:

```sh
uv sync --locked --group bundle
uv run --group bundle python scripts/build_media_tools.py \
  --output build/native/media --work-dir build/native/media-work
uv run --group bundle python scripts/build_runtime.py \
  --media-dir build/native/media --output build/native/runtime
npm ci --prefix desktop
npm --prefix desktop test
npm --prefix desktop run dist
```

The runtime build verifies and stages the exact Python and SoundFile component
notices. Native packages appear in `dist/native`. macOS produces a DMG; Windows
produces a per-user NSIS installer; Linux produces a Debian package and a
portable archive. Build outputs are deliberately separate from saved projects.

The media builder requires a new output directory. Keep its source archives,
reconstruction recipe, licenses, and manifests together when retaining a build.
The SoundFile source stage beside the runtime is also part of the native release.

## Exercise the packaged application

First verify the frozen audio service in isolation:

```sh
uv run --group bundle python scripts/smoke_runtime.py \
  --runtime build/native/runtime/cleantake-runtime \
  --report build/native/evidence/runtime.json
```

The desktop test controller needs three environment variables:

- `CLEANTAKE_APP`: absolute path to the actual packaged executable, including
  `Contents/MacOS/CleanTake` inside a macOS application bundle.
- `CLEANTAKE_TEST_WORKSPACE`: a disposable workspace, preferably with spaces
  and non-ASCII characters in its path.
- `CLEANTAKE_TEST_REPORT_DIR`: where to retain the JSON report and captures.

Run `npm --prefix desktop run test:app`. The controller launches the application
with an empty executable search path while keeping its own testing tools
available. It verifies the real audio clock, sample, saved decisions, native
menus, exports, second-instance behavior, restart, and owned-process shutdown.
Chromium sandboxing stays enabled. Linux tests require a working display and
audio server; the workflow configures dedicated test instances.

`scripts/native_ci.py install-smoke --arch arm64` exercises an actual installer
and checks that removal and reinstallation retain saved project bytes. Substitute
`x64` for an Intel/AMD target. Windows and Linux installation tests require a
disposable GitHub Actions runner so they cannot replace a local installation.

## Signing and release evidence

Ordinary development builds use ad-hoc macOS signatures and unsigned Windows
installers. They do not claim a verified publisher or macOS notarization.
The workflow's explicit signed run requires protected credentials and checks
the resulting signatures. See [signing setup](../packaging/ci/README.md).

Keep the final installer hashes and post-sign payload inventory. Electron can
re-sign nested libraries during packaging, so pre-sign runtime hashes and final
application hashes describe different stages. Publish exact corresponding source
and component notices alongside the verified installers.
