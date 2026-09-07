# Changelog

## 0.1.0

First public release of the complete local recovery workflow.

- Import up to four simultaneous recordings with immutable originals and verified caches.
- Estimate offset, clock drift and polarity; preserve manual alignment and uncertainty.
- Review dropout and clipping proposals using actual source audio; edit or create repairs.
- Compare original, repaired and donor audio at the same timeline position.
- Save revisioned projects with undo/redo, integrity checks and interrupted-job recovery.
- Navigate transcript context through a guarded turnchunk adapter with timestamp provenance.
- Export float WAV, PCM24 FLAC, aligned stems, editable Reaper envelopes and exact contributor maps.
- Create measured loudness finishing as a separate output and round-trip portable projects.
- Use the browser studio or CLI, including a licensed offline sample and reproducible evaluation.

The release outputs a 48 kHz mono timeline. Automatic suggestions require review
and can miss damage. See [evaluation](docs/EVALUATION.md) for measured behavior,
failures and claims that have not been established.
