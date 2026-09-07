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

Python dependencies are installed as separate distributions with their own
license metadata and files. They include NumPy, SciPy, SoundFile, Pydantic,
FastAPI, Uvicorn, python-multipart, Typer, Rich and
[turnchunk](https://github.com/pavangupta352/turnchunk). CleanTake uses turnchunk
0.4.1 through a guarded transcript adapter; see [the integration guide](docs/TRANSCRIPTS.md).

FFmpeg and FFprobe are required external programs. CleanTake does not bundle
their binaries. Their license terms depend on the build installed by the user.
Reaper is an optional external editor, is not bundled, and is not required to
use CleanTake. The Reaper export interoperability check is described in
[the export guide](docs/EXPORTS.md).
