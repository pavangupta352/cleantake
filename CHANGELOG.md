# Changelog

## 0.2.2

- Show the saved replacement source and full original filename beside Accept,
  with separately labeled project and recording time ranges.
- Account for the saved source offset and clock drift in the recording range.
- Mark unsaved repair fields clearly so they cannot be confused with the saved
  replacement being reviewed.
- Keep acceptance unavailable without a saved, aligned source covering the
  complete repair range.

The recovery engine, dependency versions and existing demo media are unchanged.

## 0.2.1

- Preserve source-marked estimated times in Azure phrases, Deepgram paragraphs,
  AssemblyAI word groups and the other supported transcript layouts, including
  all three estimate aliases and words with missing endpoints.
- Associate each timing marker with its selected source entry or speaker group.
  Adjacent or overlapping precise turns and unused recognition alternatives no
  longer inherit another passage's uncertainty.
- Reject malformed selected annotation containers with a useful import error.
  Retain explicit units, raw metadata and missing endpoints. Transcript import
  and navigation leave sample-based audio edits unchanged.

The correction applies to new imports. Previously saved project and archive
transcripts keep their stored labels; reopening does not refresh them. Importing
the same file again adds another entry rather than replacing it.

The recovery engine and dependency versions are unchanged. A separate
[natural-fault intake](eval/natural/README.md) records a publisher-documented
candidate; it contains no evaluated audio or participant outcomes.

## 0.2.0

- Bundle the browser runtime, Python processing engine, media tools and sample
  into native desktop distributions for macOS, Windows and Linux.
- Open a ready local studio with native windows, menus and file-save dialogs.
  Install the sample once and preserve projects when the app is reinstalled.
- Route native Undo/Redo to repair decisions while retaining normal text editing.
- Stop owned workers and media tools after service crashes, recover interrupted
  jobs, and retain the last saved project revision.
- Verify real frozen and installed workflows with developer tools absent from
  the application's search path. Retain exact source, license and build records.

All six native targets passed frozen processing, installed-app editing and
export, dependency inspection, and saved-project retention through removal and
reinstallation. See the [validation record](docs/VALIDATION.md#native-desktop--020).
Mac builds are ad-hoc signed and not notarized; Windows installers are unsigned.
The [desktop guide](docs/DESKTOP.md) explains installation and publisher trust.

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
