# Local studio API

Implementation contract, version 1. The Python project records in `cleantake.models` are the authority for field names. All routes below are under `/api`; successful JSON responses use ordinary objects, not nested `data` wrappers.

## Session and errors

The launcher opens `http://127.0.0.1:PORT/#token=SESSION_TOKEN`. The studio reads the fragment, saves the token in session storage, then removes the fragment from the address bar. Requests use `X-CleanTake-Token`. The process token is never placed in a query string, printed in access logs, or sent to external resources. Bind only loopback. Validate Host and Origin in addition to the token. The studio is served from the same origin; development proxying preserves that boundary.

`GET /health` is the sole unauthenticated API route: `{ "status": "ok", "version": "…" }`. It includes no workspace, token or project data.

Errors: `{ "error": { "code": "invalid_request", "message": "…" } }`. Validation uses 422, missing objects 404, invalid session 401, forbidden host/origin 403, revision/project-busy conflicts 409, oversized uploads 413. Error messages must be useful without disclosing server file locations, transcript contents or access tokens. Non-JSON malformed requests follow the same envelope. Unknown `/api/` routes return JSON 404 and never the SPA document.

## Project shelf and editing

| Method and route | Request | Success response |
|---|---|---|
| GET `/projects` | — | `{ "projects": ProjectSummary[] }` |
| POST `/projects` | `{name}` | 201 PublicProject |
| GET `/projects/{id}` | — | PublicProject, plus `can_undo` and `can_redo` booleans |
| PATCH `/projects/{id}` | `{name?, primary_source_id?, expected_revision}` | Updated PublicProject |
| DELETE `/projects/{id}` | `{expected_revision}` | 204, selected owned project only |
| POST `/projects/{id}/sources` | Multipart `file`, optional `name`, `channel`, `stream` | 202 Job; actual import/decoding runs in job |
| PATCH `/projects/{id}/sources/{source_id}` | `{name?,speaker?,alignment?,expected_revision}` | Updated PublicProject; alignment override status becomes manual |
| POST `/projects/{id}/analyze` | `{expected_revision}` | 202 Job |
| POST `/projects/{id}/repairs` | `{start_frame,end_frame,source_id,kind:'manual',gain_db?,fade_ms?,expected_revision}` | PublicProject with a proposed manual repair |
| PATCH `/projects/{id}/repairs/{repair_id}` | `{status?,source_id?,start_frame?,end_frame?,gain_db?,fade_ms?,expected_revision}` | Updated PublicProject |
| POST `/projects/{id}/undo` or `/redo` | `{expected_revision}` | Updated PublicProject |
| POST `/projects/{id}/transcript` | `{text,source_id,filename,time_unit?,expected_revision}` | Updated PublicProject |

The first imported source becomes primary. Changing primary resets alignment and analysis explicitly because project time changes; the studio must explain that effect before applying it to a project with decisions. Naming/speaker changes do not change audio. A source alignment change invalidates affected repair decisions and previews; retaining an accepted edit against a different clock silently would be incorrect.

A manual `alignment` patch accepts only `offset_seconds`, `drift_ppm` and `polarity` (−1 or 1). The service sets `status: 'manual'`; clients cannot supply computed confidence or anchor counts.

`PublicProject` fields: `schema_version`, `id`, `name`, `created_at`, `updated_at`, `revision`, `sample_rate`, `primary_source_id`, `duration_frames`, `sources`, `repairs`, `transcripts`, `warnings`, `status`, `error`. Public sources include id/name/original filename/SHA-256/import time, audio metadata, alignment and optional speaker; they never include `original_path` or cache `path`. Audio metadata retains original rate/channels and selected stream/channel. Repairs match `RepairRecord`. All times used for edits are integer frames on the project rate.

Project summaries contain id/name/timestamps/revision/status/duration_frames/source_count/repair_count. Clients refresh the full project after a completed job. Revision conflicts cause refresh and a clear message, not a silent retry that overwrites a newer decision.

## Jobs

`Job` fields: `id`, `project_id`, `operation` (`import`, `analyze`, `export`, `archive_import`), `status` (`queued`, `running`, `completed`, `failed`, `cancelled`, `interrupted`), `progress` (0–1 or null), `message`, `created_at`, `updated_at`, `result` (object or null), `error` (safe message or null).

`GET /jobs/{id}` returns Job. `POST /jobs/{id}/cancel` requests cancellation and returns Job. A cancellation request can race with completion; report the actual terminal state. Persist jobs, mark orphaned running jobs interrupted on startup, and remove incomplete outputs. Use bounded worker count and one active writer per project. Do not use fabricated percentage progress; null and a meaningful stage are correct when total work is unknown.

## Waveforms and listening

`GET /projects/{id}/peaks?source_id=ID&start_frame=0&end_frame=N&bins=1200` returns `{source_id,start_frame,end_frame,sample_rate,min: number[],max: number[],coverage: [start_frame,end_frame],revision}`. Bin count is 1–4096. The source uses the project timeline and saved transform; an unaligned source is displayed in its own clock with an explicit `aligned:false` flag. An output lane can request `mode=repaired` in place of a source. Arrays reflect actual PCM and min/max, not generated drawing data.

`GET /projects/{id}/audio?mode=original|repaired|source&source_id=ID&start_frame=0&end_frame=N` returns a mono WAV excerpt at the project sample rate. Maximum request duration is 120 seconds; invalid/out-of-duration bounds fail clearly. `source_id` is required only for source mode. Original means primary, repaired means accepted edits, source means the aligned selected recording. Uncertain alignment cannot pretend to be a synchronized audition: reject it until the editor supplies manual alignment, or explicitly request a separate own-clock audition.

Audio response headers identify `X-CleanTake-Start-Frame`, `X-CleanTake-End-Frame`, and `X-CleanTake-Revision`. These windows permit bounded-memory playback without generating a full multihour mix after every small edit. The studio uses Web Audio, schedules consecutive windows on one clock, keeps at most a small number of decoded buffers and cancels stale requests when the selected project/revision/mode changes. Switching Original/Repair/Source preserves current project time. Seeking or changing an edit must not leave a second player running.

## Export and portability

`POST /projects/{id}/exports` accepts `{format:'wav'|'flac',finish:false,expected_revision}` and returns a job. Successful `result` is `{export_id,revision,artifacts:[{name,size,media_type}],warnings}`. Rendered dialogue, source-map JSON, aligned stems and Reaper project are part of the export. Finished output is separate from the unmastered repair mix.

Artifact bytes are served by `GET /projects/{id}/exports/{export_id}/{artifact}`. The normal session header is accepted for programmatic clients. For a browser save action, `POST` to the same artifact path plus `/ticket` issues `{url,expires_at}` with a short-lived, unguessable token scoped to that exact project/export/artifact. That token cannot read another file or call mutation endpoints. Support HTTP range requests; disable access logging of ticket query strings; set `Referrer-Policy: no-referrer`.

`POST /projects/{id}/archive` creates a portable project archive as an export job. `POST /projects/import` accepts a multipart archive and imports it as a job into a new generated project ID. Never preserve a foreign project ID that could overwrite existing work. Validate all archive members before extraction and impose file-count and expanded-size bounds. Source files retain original hashes. The archive operation is an explicit inclusion of original recordings; the studio names that fact before downloading it.

## Limits and diagnostics

Defaults must be centralized, surfaced in health/settings where useful, and tested: four sources per project, upload size limit, maximum recording duration, preview window 120 seconds, waveform bins 4096, worker count and expanded archive size. Do not label a hard limit “unlimited.” FFmpeg discovery and unsupported input errors identify a recovery action. Empty project, one source, uncertain alignment, missing backup and no intact source each have a distinct recoverable state.
