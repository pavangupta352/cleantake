# Third-party materials

CleanTake's source code is MIT licensed. The following materials retain their
own licenses and notices.

- **AMI Meeting Corpus**, AMI Project Consortium: the two bundled 20-second
  ES2004a recordings are Creative Commons Attribution 4.0 International.
  [Attribution and modifications](src/cleantake/assets/demo/ATTRIBUTION.md),
  [source URLs and hashes](src/cleantake/assets/demo/manifest.json).
  The sample command adds a labeled half-second dropout to a copy of the headset
  excerpt. No endorsement by the corpus creators or participants is implied.
- **React, React DOM and Scheduler**: MIT, Meta Platforms, Inc. and affiliates.
- **Lucide**: ISC, Lucide Icons and Contributors; certain icons also retain the
  MIT notice of the Feather project, Cole Bemis.
- **Vite browser runtime helpers**: MIT. The build includes Vite's complete
  distributed license notices alongside the studio.

Full notices for bundled browser code are in
[the packaged notice file](src/cleantake/static/THIRD_PARTY_NOTICES.txt).
`scripts/build_release.py` regenerates that file from the locked packages.

Python dependencies retain their own license metadata and files. They include
NumPy, SciPy, SoundFile, Pydantic,
FastAPI, Uvicorn, python-multipart, Typer, Rich and
[turnchunk](https://github.com/pavangupta352/turnchunk). CleanTake uses turnchunk
0.4.1 through a guarded transcript adapter; see [the integration guide](docs/TRANSCRIPTS.md).

## Desktop distributions

The self-contained desktop application includes Electron and Chromium, CPython,
the locked Python dependencies, libsndfile and its codec libraries, and native
FFmpeg/FFprobe executables. Their licenses are independent of CleanTake's MIT
license. Installed resources retain Electron's `LICENSE.electron.txt`,
`LICENSES.chromium.html`, Python distribution metadata and complete component
notices beneath the backend's `_internal/licenses` directory.

- **Electron and Chromium:** the unmodified Electron distribution includes its
  own complete component notices. The application icon uses Lucide's AudioLines
  icon and retains its distributed Lucide/Feather notices.
- **CPython and embedded components:** the exact standalone interpreter's
  platform metadata and notices are retained, including libraries statically
  linked into Python extensions. [Pinned build and notice provenance](packaging/python/README.md).
- **SoundFile / libsndfile:** the native library retains LGPL and individual
  codec-component notices. Each release includes matching source archives,
  upstream build recipes and applicable Windows patches. The dynamic library
  can be rebuilt and replaced in a local application build.
  [Source, licenses and replacement instructions](packaging/soundfile/README.md).
- **FFmpeg / FFprobe:** CleanTake's native builds use the verified official
  FFmpeg source with LGPL configuration, without GPL, nonfree or autodetected
  external components. Complete notices, effective build flags, corresponding
  source and reconstruction instructions accompany the release.
  [Media build and licensing](packaging/ffmpeg/README.md).
- **PyInstaller:** the frozen backend retains the bootloader's license and
  distribution exception, alongside dependency notices.

Native releases publish the corresponding-source package next to the installers.
The runtime manifests identify exact components and source hashes; final
installer checksums cover the application after platform packaging and signing.

## Python package and optional external tools

The wheel/source installation installs Python dependencies separately and uses
the user's FFmpeg/FFprobe executables. That route does not bundle media binaries;
their license terms depend on the installed build. The desktop route includes
its required application runtimes and media tools.

Reaper is an optional external editor, is not bundled, and is not required to
use CleanTake. The Reaper export interoperability check is described in
[the export guide](docs/EXPORTS.md).
