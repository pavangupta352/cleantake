# CleanTake architecture

Status: implementation plan, 8 September 2026. Maintainer: Pavan Gupta.

## Outcome and boundary

CleanTake recovers a damaged passage from an intact simultaneous recording, lets an editor review the replacement in context, and exports finished dialogue with a verifiable source map. A complete supported workflow is the release target. A processing demo alone does not satisfy it.

Start with two to four audio sources from the same performance. Import audio and video supported by the installed FFmpeg build; store actual decoded metadata. Manual source labels and speaker names are authoritative. Automatic speaker identification is not necessary for the recovery path. A source without a confident common time basis requires manual alignment before it may supply a repair.

The recommended distribution is an installable Python package containing the built browser studio and a CLI. `cleantake studio` serves only loopback and opens the studio. `cleantake repair` supports a reproducible file-to-export workflow. Desktop packaging can wrap the same engine without changing project or edit semantics.

## Alternatives considered

| Approach | Benefit | Cost | Decision |
|---|---|---|---|
| Local Python engine and browser studio | Inspectable scientific processing, portable CLI, reuse of turnchunk, fast correctness iteration | Python/FFmpeg setup needs excellent packaging | Selected implementation direction |
| Native Rust engine and desktop shell | Native playback and tighter distribution | New DSP and packaging work slows validation; no Rust toolchain currently installed | Keep as a future packaging/performance option |
| Browser-only processing | Link-based first use | Media codec, memory, long-session and durable-file limits complicate reliable rescue | Use browser for the interface, processing locally |

## Modules

- `src/cleantake/engine/`: pure numeric alignment, damage evidence, candidate selection and repair rendering. No HTTP, UI or project storage dependency.
- `src/cleantake/media.py`: inspect and decode user media with argument-list subprocesses, hashes, channel selection and bounded disk-backed caches.
- `src/cleantake/models.py`: versioned persisted project, source, repair, transcript and export records. Validation belongs at the boundary.
- `src/cleantake/projects.py`: safe project creation, import, atomic revisions, source integrity, analysis orchestration, review history, recovery and deletion.
- `src/cleantake/exports.py`: rendered WAV/FLAC, aligned source stems, source map and Reaper project; provenance-preserving portable archive.
- `src/cleantake/transcripts.py`: guarded turnchunk adapter; raw word timing and explicit units retained independently.
- `src/cleantake/server/`: loopback API, streamed uploads, bounded jobs, status/cancellation and built studio hosting.
- `src/cleantake/cli.py`: diagnostic, project creation, analysis, repair, render, export and studio entry points.
- `studio/`: React/TypeScript editor, real waveform peaks, source comparison, repair queue, decision history, transcript navigation, recovery and export controls.
- `tests/`: numerical, project, media, security, integration and distribution checks. `studio/e2e/` exercises the real local server.

## Media and timeline contract

Keep original files immutable in the project. Record SHA-256, original filename, selected audio stream/channel, sample rate and frame count. Decode to a documented mono working timeline; record downmix/channel selection rather than implying a stereo-preserving mix. Float32 PCM disk caches avoid loading all long recordings into RAM. Decode caches can be rebuilt from unchanged originals.

The primary recording defines project time, duration and silence. Do not shorten the performance. All edit ranges are integer frames on the working sample rate (48,000 Hz). Original decoded-source positions are derived with the saved sample-rate ratio and alignment transform. Lossy source formats are traceable to their decoded samples; do not promise reversal to encoded bytes.

For a candidate recording, source time = reference time × (1 + drift_ppm / 1,000,000) + offset_seconds. Positive offset means the corresponding sound is later inside the candidate file. Store this sign convention in JSON and tests. A negative offset leaves an uncovered prefix; a short backup leaves an uncovered suffix. Neither may supply replacement samples outside actual coverage.

Alignment estimates include confidence, supporting anchor count and residual timing error. Correlate band-limited speech and/or energy envelopes for coarse offset, refine multiple speech-bearing anchors, and fit drift robustly. Reject silence, unrelated sources, ambiguity, inadequate overlap and inconsistent anchors. Permit explicit offset/drift overrides with a manual origin marker.

## Engine interface

Array inputs are finite one-dimensional floating PCM; callers use memory maps for full recordings. All functions document units and never mutate input arrays.

```python
estimate_alignment(reference, candidate, sample_rate) -> Alignment
sample_aligned(candidate, start_frame, end_frame, sample_rate, alignment) -> ndarray
find_repairs(reference, candidates, sample_rate) -> list[RepairProposal]
render_range(reference, candidates, repairs, start_frame, end_frame, sample_rate) -> ndarray
```

`Alignment` has `offset_seconds`, `drift_ppm`, `confidence`, `anchors`, `residual_ms`, `status` (`aligned`, `uncertain`, `manual`, `reference`) and `polarity` (1 or -1).

Each candidate has `source_id`, `samples` and `alignment`. Each proposal has `start_frame`, `end_frame`, `kind` (`dropout`, `clipping`, `noise`, `manual`), `source_id` or null, `confidence`, `reason`, `alternatives` and `status` (`proposed`, `accepted`, `rejected`, `unresolved`). Repairs retain independent gain and fade parameters. Saved source IDs are generated identifiers, never filesystem paths.

Treat a dropout as damaged only when cross-source evidence distinguishes missing signal from shared silence. Clipping requires actual overload/plateau evidence. Noise suggestions need relative source evidence and cautious confidence. A louder source alone is not a better source. Keep uncertain or no-intact-source regions in review; never convert them to confident fixes.

## Repair and finishing semantics

Suggestions do not become accepted edits silently in the studio. Editors can accept/reject individual ranges, select an alternative, adjust boundaries, create manual repairs, and undo/redo. A CLI unattended repair explicitly documents whether it accepts confident proposals; unresolved ranges stay in original audio and appear in the report.

Retain the primary outside accepted repair ranges and their documented crossfade support. Compare sources using time-aligned previews. Match levels from usable surrounding speech with bounded gain; avoid boosting silence/noise. Crossfades preserve length. Optional finishing is a separate reversible export stage, with measured loudness/peak results and a no-finishing option. No voice generation, language rewriting or automatic dead-air removal.

Source maps enumerate primary spans and both contributors in crossfades, including original decoded frame ranges, transformation, gain and interpolation. A map that attributes a mixed seam to one source is incomplete. Include processing settings, version and input hashes. Export aligned stems and an editable Reaper project plus a JSON decision list, so audio users can continue outside CleanTake.

## Durable local projects

Versioned JSON manifests, immutable original media and atomically replaced current revisions. Keep undo/redo states bounded and recoverable. Save source references relative to project root so archives are portable. Validate schema version and refuse unsupported future versions clearly. Detect changed or missing sources before processing; offer explicit relinking with hash validation. Never silently match a same-named file.

Heavy work runs as bounded cancellable jobs, one writer per project. Persist job state and recover interrupted work to a visible interrupted state on restart. Outputs are temporary until successfully completed; failed/cancelled jobs cannot appear as successful exports. Delete only a selected owned project after explicit UI confirmation.

## Local API and trust boundary

Bind to 127.0.0.1 by default. Reject non-local Host headers and untrusted browser origins, require an unguessable session token on mutations and private media requests, and avoid wildcard CORS. Upload bytes through the API; do not expose arbitrary filesystem reads by accepting paths. Validate IDs, multipart limits, archive members, filenames, numeric ranges and schema before filesystem access. Resolve paths under the owned workspace; block traversal and symlink escape. Limit simultaneous jobs and subprocess execution duration. Never interpolate filenames into a shell command.

Preview/media endpoints support range requests and project-scoped identifiers. The frontend never receives private filesystem paths or credentials beyond its own session token. No telemetry, automatic uploads, cloud accounts or outbound processing requests.

## Transcript integration

Pin a tested turnchunk version through a small adapter. The known 0.4.1 generic parser infers units by magnitude even for explicit `start_ms`; bypass that path for explicit units and reject ambiguous generic timing unless the importer declares units. Preserve raw words/segments, source ID, transcript revision and estimated-time flags. Show estimates as estimates. Imported text is untrusted content and rendered as text. Optional transcription can be added behind a separately verified local adapter; it must not be required to rescue audio.

## Definition of release readiness

See [validation](VALIDATION.md) for measurable gates and [roadmap](ROADMAP.md) for delivery order. Passing generated fixtures alone does not establish natural human listening quality or superiority to an editor. Current external evaluations and genuine limits remain explicit. Code, documentation, distribution and demo claims must agree before a release is called complete.

