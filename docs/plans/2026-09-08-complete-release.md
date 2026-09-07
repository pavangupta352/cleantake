# CleanTake complete release implementation plan

**Goal:** Deliver and publish a complete local dialogue-rescue studio with reproducible source provenance and portable exports.

**Architecture:** A pure numeric recovery engine consumes disk-backed PCM. A versioned project service owns media and edits, with CLI and loopback API as clients. The studio reviews actual evidence and audio from that service.

**Tech stack:** Python ≥3.12, NumPy/SciPy, SoundFile, FFmpeg, Pydantic, FastAPI, Typer; React/TypeScript/Vite. Lock resolved versions. Pin turnchunk 0.4.1 behind a guarded adapter.

**Spec:** [Architecture](../ARCHITECTURE.md), [validation](../VALIDATION.md), [product](../../PRODUCT.md).

## Global constraints

- Pavan Gupta is maintainer and commit author. Preserve third-party license obligations.
- Two to four simultaneous recordings; original media immutable; local processing; no cloud dependency.
- Working sample rate 48,000 Hz. Edit bounds are integer frames, start inclusive/end exclusive.
- Candidate time = reference time × (1 + drift_ppm / 1,000,000) + offset_seconds.
- Suggestions require review in the studio; actual recorded donor audio only. Preserve timing, overlap and laughter.
- Core modules must not import HTTP/UI. Project services serialize engine contracts explicitly.
- Failed, uncertain or interrupted operations never become successful results. All external validation claims require actual evidence.
- Each task follows a failing behavioral test, implementation, passing targeted tests and fresh review. Changes to documents/config alone need no mirrored tests.

## Task 1: Numerical synchronization and recovery engine

**Files:** `src/cleantake/engine/{__init__,contracts,alignment,detection,render}.py`; `tests/engine/test_{alignment,detection,render}.py`.

**Consumes:** finite one-dimensional NumPy float arrays, including memory maps; rate integer.

**Produces:** Import these from `cleantake.engine`:

```python
@dataclass(frozen=True)
class Alignment:
    offset_seconds: float = 0.0
    drift_ppm: float = 0.0
    confidence: float = 0.0
    anchors: int = 0
    residual_ms: float = 0.0
    status: str = "uncertain"
    polarity: int = 1

@dataclass(frozen=True)
class CandidateTrack:
    source_id: str
    samples: np.ndarray
    alignment: Alignment

@dataclass
class RepairProposal:
    start_frame: int
    end_frame: int
    kind: str
    source_id: str | None
    confidence: float
    reason: str
    alternatives: list[dict] = field(default_factory=list)
    status: str = "proposed"
    gain_db: float = 0.0
    fade_ms: float = 12.0

estimate_alignment(reference, candidate, sample_rate) -> Alignment
sample_aligned(candidate, start_frame, end_frame, sample_rate, alignment) -> np.ndarray
find_repairs(reference, candidates, sample_rate) -> list[RepairProposal]
render_range(reference, candidates, repairs, start_frame, end_frame, sample_rate) -> np.ndarray
```

- [ ] Write tests with deterministic non-periodic, speech-band fixtures. Check +0.375 s and −0.220 s sign conventions, 120 ppm drift, inverse polarity, different gains, short coverage and unrelated/silent rejection. Expected shifts are injected literals, not outputs of production helpers.
- [ ] Run `uv run pytest tests/engine/test_alignment.py`; record missing behavior before implementation. Implement coarse correlation, multiple robust anchors, confidence, drift and coverage-aware sampling. Keep full-recording copies bounded.
- [ ] Write damage tests: missing interval with actual intact candidate must propose that candidate; shared silence/clean primary must not produce repairs; clipped donor cannot rescue a clipped primary; unavailable/uncertain candidate cannot rescue. Test natural low-energy segments against false positives.
- [ ] Implement conservative frame evidence and interval merging, candidate scores, bounded contextual gain matching. Make no arbitrary noise-superiority claim; uncertain regions remain reviewable.
- [ ] Write render tests that accept a literal donor interval, compare exact untouched primary regions, verify coverage/gain/fades and unchanged duration. Reject overlapping, out-of-range or unknown-source accepted edits. Unresolved/rejected/proposed edits do not render as accepted changes.
- [ ] Implement deterministic chunk rendering and exported contributor-span information (may be an additional documented public helper). Compare whole rendering against concatenated subranges; they must agree at chunk boundaries.
- [ ] Run all engine tests, lint and review against architecture. Record actual measured limits and remaining alignment uncertainty.

## Task 2: Guarded transcript integration

**Files:** `src/cleantake/transcripts.py`, `tests/test_transcripts.py`, `examples/transcripts/`.

**Consumes:** raw transcript string, source identifier, filename/format hint and optional declared generic unit.

**Produces:** `import_transcript(text: str, source_id: str, filename: str, *, time_unit: str | None = None) -> dict`. Returned record: `id`, `source_id`, `format`, `raw_text`, `turns` (text, speaker, start_ms/end_ms nullable, time_estimated), `words` (original word timings and provenance), `warnings`. Dict must be JSON safe and finite.

- [ ] Regression test explicit `{start_ms:1000,end_ms:2000,text:'hello'}` stays 1000/2000; generic `{start:1,end:2}` without declared units returns a clear validation error. With seconds it becomes 1000/2000.
- [ ] Test actual VTT/SRT, Whisper segments with words, unknown/unestimated timing and malicious text rendered as plain content by downstream consumers. Preserve negative/invalid timing as a clear error; do not silently coerce.
- [ ] Observe failures, implement a small turnchunk adapter, bypass its explicit-unit generic bug, and preserve raw word structures separately before its merging discards them. Do not vendor or rewrite the entire third-party parser.
- [ ] Run `uv run pytest tests/test_transcripts.py`, lint and review; document provenance limitations in an integration guide.

## Task 3: Media ingestion and versioned projects

**Files:** `src/cleantake/{models,media,projects}.py`, `tests/test_{media,projects}.py`.

**Consumes:** filesystem Path from trusted CLI/import coordinator, user-visible name, selected stream/channel. Engine API in Task 1 and transcript result in Task 2.

**Produces:** `ProjectStore(root: Path)` with `create(name: str)`, `list()`, `get(project_id)`, `import_source(project_id, path, *, name=None, channel=None)`, `analyze(project_id)`, `update_repair(project_id, repair_id, changes, expected_revision=None)`, `add_repair(...)`, `undo(project_id)`, `redo(project_id)`, `delete(project_id)` and `source_path(project_id, source_id, kind)`.

Project JSON includes schema_version=1, id, name, created_at/updated_at, revision, sample_rate=48000, primary_source_id, duration_frames, sources, repairs, transcripts, warnings and status. Source includes id/name/original_filename/sha256/audio cache metadata/alignment/speaker. Repair includes generated id plus Task 1 fields. File locations remain relative and are not exposed in API public views.

- [ ] Test real generated WAV ingestion and a small FFmpeg-encoded video, Unicode names, unequal sample rates, stereo channel choice, duplicates, empty/non-media files and source hash mismatch.
- [ ] Test create/import/reopen/edit/undo/redo with literal bounds; validate UUID-like IDs, finite numbers, known source and primary duration. Reject unknown future schema and conflicting revisions.
- [ ] Implement typed models, checked argument-list subprocess decode, original copying and bounded PCM caching. Use atomic metadata/output replacement and a per-project writer lock. No arbitrary-path access through source ID.
- [ ] Connect analysis to pure engine, persist transform/proposals, retain status and errors across failures. Convert frames and model fields explicitly. Cancellation must leave originals and prior revision intact.
- [ ] Run real media and project tests plus lint; review atomicity, invalid-state behavior, memory use and transcript boundaries.

## Task 4: Render, export and portable projects

**Files:** `src/cleantake/exports.py`, `tests/test_exports.py`, `docs/EXPORTS.md`.

**Consumes:** validated saved project, accepted edits and immutable source caches.

**Produces:** `export_project(store, project_id, output_dir, *, format='wav', finish=False) -> dict`, plus project archive import/export methods. Render output, `source-map.json`, aligned stem WAV files and `session.rpp`; optional finished audio measured independently.

- [ ] Test rendered donor content and retained primary samples, duration, hash provenance, both contributors in fades, source-frame mapping and exact export settings.
- [ ] Implement chunked audio writing with temporary output and final rename. Name each stem safely, escape Reaper strings, include edit gains and joins. Validate all sources before output.
- [ ] Test project archive round-trip/reopen with preserved choices. Reject traversal, absolute paths, symlinks, oversized archives, duplicate members and missing media. Stream members with total extracted-size bounds.
- [ ] Implement optional FFmpeg two-pass loudness finishing with explicit target and true-peak ceiling; parse measured result, preserve unmastered mix and provenance processing stage. Empty/silent audio must have a clear result.
- [ ] Run export/media integration tests, independently decode every audio artifact and verify exported Reaper/JSON references resolve.

## Task 5: Loopback API and durable jobs

**Files:** `src/cleantake/server/{__init__,app,jobs,security}.py`, `tests/server/test_{api,jobs,security}.py`.

**Consumes:** `ProjectStore`, export service, transcript adapter. `create_app(workspace: Path, token: str | None = None) -> FastAPI`.

**Produces:** JSON API under `/api`; token handshake carried by launch fragment and request header `X-CleanTake-Token`. GET health is public and discloses no project data. Other routes require token and valid loopback Host; browser origins must match allowed local studio origin. GET media may use a short-lived scoped token, never arbitrary file path.

Routes: GET/POST `/projects`, GET/PATCH/DELETE `/projects/{id}`, POST `/projects/{id}/sources`, POST `/projects/{id}/analyze`, GET `/jobs/{id}`, POST `/jobs/{id}/cancel`, PATCH/POST `/projects/{id}/repairs[/repair_id]`, POST `/projects/{id}/undo|redo`, POST `/projects/{id}/transcript`, GET `/projects/{id}/peaks|audio`, POST `/projects/{id}/exports`, GET `/projects/{id}/exports/{export_id}/{artifact}`. Lock exact payloads in `docs/API.md` before studio implementation.

- [ ] Exercise real temporary project uploads, analysis job, repair revision, preview/range download and export using HTTP test client. Expected results derive from generated source samples, not mocked service calls.
- [ ] Test missing/wrong token, foreign Origin/Host, traversal, invalid sizes, invalid project/source IDs, malformed JSON/media, concurrent mutation and export/download authorization.
- [ ] Implement streamed upload limits, persistent job lifecycle (queued/running/completed/failed/cancelled/interrupted), cooperative cancellation and one writer per project. Cleanly shut down resources.
- [ ] Serve bundled studio only after API routing; unknown API routes must not fall through to HTML. Content security headers and user-facing error codes must be clear.
- [ ] Run server tests and review threat boundaries and interrupted-job recovery.

## Task 6: CLI and reproducible sample path

**Files:** `src/cleantake/cli.py`, `tests/test_cli.py`, `examples/README.md`, `scripts/`.

**Consumes:** project/store/export APIs. CLI version reads package metadata.

- [ ] Test help/version/doctor, create/import/analyze/repair/export/studio commands, missing FFmpeg and invalid files with meaningful nonzero exits.
- [ ] Implement `cleantake repair MAIN BACKUP... --output DIR` with explicit automatic acceptance of confident suggestions, preserved unresolved report and reusable project path. Never overwrite existing user outputs without an explicit flag.
- [ ] Implement `cleantake studio --workspace PATH --port PORT --no-browser` binding loopback; open launch URL with token in fragment. Do not print or persist secrets in normal logs.
- [ ] Add a numerical fixture generator and licensed sample preparation script with explicit source URLs/hash/modification/license, respecting reserved evaluation split.
- [ ] Run CLI integration from installed package, not only import tests.

## Task 7: Review studio

**Files:** `studio/src/`, `studio/e2e/`, `studio/package.json`, `studio/vite.config.ts`, `studio/tsconfig.json`, `docs/API.md`, `DESIGN.md` after final UI review.

**Consumes:** exact HTTP contract Task 5. Do not fabricate UI responses or waveforms. Real sample project can demonstrate without user files.

- [ ] Resolve UI direction with Impeccable, record surface brief and read craft floor. Keep task-operating mode and accessible alternatives to canvas interaction.
- [ ] Build project shelf/new project and drop import, real upload/job progress, source identity/channel/primary selection and synchronization review.
- [ ] Build waveform timeline with meaningful zoom/seek, play/pause and Original/Repair/Source modes. Changing comparison must preserve playback time, with one active audio source. Space shortcut must not steal typing input.
- [ ] Build repair queue/selection, source alternatives, accept/reject/all-safe review, start/end/gain/fade controls, manual repair creation, undo/redo and saved revision feedback.
- [ ] Build transcript import/speaker labeling/navigation, explicit uncertain/alignment/manual states, failure recovery, project reopen and export selections/downloads.
- [ ] Real-server browser E2E exercises import→analyze→audition→edit→save/reopen→export. Check keyboard, visible focus, source labels, token handling and no console errors. Responsive desktop and narrow-screen workflows remain usable.
- [ ] Inspect desktop/mobile in a batched screenshot pass, fix together, confirm once. Run detector, fresh-context finish review, resolve material findings and document actual built design.

## Task 8: Corpus evaluation and reliability

**Files:** `eval/`, `tests/test_long_recordings.py`, `docs/EVALUATION.md`.

- [ ] Reserve AMI IS1009a for evaluation before tuning, use ES2004a for development; record any later split change. Keep originals private/untracked until redistribution provenance is verified.
- [ ] Create manifest-driven alignment/repair runs with independently injected offset, drift, clipping, dropout and all-source-damage. Do not use selected faults as evidence of organic damage success.
- [ ] Measure error, false proposals, coverage, content retention, provenance and processing resources; save exact revision and failures. Exercise interruption/laughter/overlap clips without automatic removal.
- [ ] Run a documented long-session case with memory and cancellation measurements. Improve only measured resource defects and re-run relevant tests.
- [ ] Exercise current Cleanroom baseline on applicable work; document a GUI/library harness where CLI lacks multitrack. Obtain actual independent listening/editor outcomes before claiming preference or time advantage; otherwise keep those explicit open gates.

## Task 9: Distribution and release materials

**Files:** `.github/workflows/`, issue templates, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md, README.md, docs installation/user guides, scripts/build-release, third-party notices.

- [ ] Build studio, copy into package assets in release build, build wheel/sdist, install in a fresh environment and complete real repair plus packaged studio smoke.
- [ ] Configure Linux/macOS/Windows Python checks, frontend check/build and real-media tests; run Actions and inspect actual results. Pin action revisions and lock files.
- [ ] Create accurate README with usable quickstart, audible demonstration, actual screenshots, recovery/source-map explanation, supported media/setup and honest limitations. Link real turnchunk integration example.
- [ ] Produce demo from actual exported result, label injected faults and any manual intervention, include licensing and reproducibility. Prepare release assets/checksums and concise launch copy without fabricated adoption or endorsements.
- [ ] Review license obligations for dependencies and any shipped binaries/media. No secret/local path/private research in built artifacts or public history.
- [ ] Publish repository and verified release under pavangupta352. Repository/commits are authorized; unrelated external messaging requires concrete user direction.

## Task 10: Independent final review and completion audit

- [ ] Fresh reviewer checks product contract, code, tests, package and outstanding material risks across final branch.
- [ ] Address material findings in one coordinated fix batch, verify targeted regressions and re-review fixes.
- [ ] Run complete meaningful checks once after final changes, inspect GitHub workflow outcomes and release artifacts.
- [ ] Reconcile every roadmap gate, update memory/progress and public status to actual evidence. Leave goal active if required work remains. Do not use 'perfect', benchmark preference or production-ready as substitutes for measured evidence.

