# Build and release roadmap

Every stage produces working, testable software. The full release requires the complete import–repair–review–export workflow.

- [x] Read and reconcile the source research, conversation, portfolio integration notes and PDF.
- [x] Define the product, architecture, ownership and validation contract.
- [x] Recovery engine: offset/drift, evidence-based damage proposals, actual source replacements and traceable seams.
- [x] Durable projects: media ingestion, immutable sources, saved analysis, decisions, undo/redo, integrity and cancellation.
- [x] Local service and CLI: secure loopback studio, real job lifecycle, bounded file processing and clear diagnostics.
- [x] Review studio: real waveforms and audio, keyboard controls, source comparison, manual correction, transcript context and exports.
- [x] Portable outputs: WAV/FLAC, source map, aligned stems, Reaper project and reopenable project archive.
- [x] Evaluation: generated edge cases, real simultaneous microphone recordings, separate evaluation splits and long-session resource checks.
- [x] Distribution: tested clean installation, bundled studio, cross-platform CI, licenses, contribution/security guides and release checksums.
- [x] Launch materials: accurate README, real before/after audio and walkthrough, sample project, feature/limitation matrix and reproducible evaluation instructions.
- [x] Independent review and release: resolve material findings, verify every advertised path, publish verified artifacts and record remaining external validation honestly.

Features enter the release because they complete recovery or make it dependable. Cloud accounts, collection search, billing, social posting, general video editing and unrelated portfolio infrastructure do not belong in this build.


Release checks passed for the full workflow, corpus evaluation, licensed demo, independent reviews, clean installation and native CI. [Version 0.1.0 is published](https://github.com/pavangupta352/cleantake/releases/tag/v0.1.0) with the installable wheel, source archive, portable demo and SHA-256 checksums. See the [validation record](VALIDATION.md) for exact platforms and results. Broader listening and editor-time claims remain separate evidence work; see the [evaluation report](EVALUATION.md).

## Desktop distribution · 0.2.0

Version 0.2.0 adds an installed application with its own browser, processing
runtime, audio tools and sample. The recovery workflow remains shared with the
CLI edition. All six targets have passed actual native installation checks.

- [x] Bundle the processing engine, media tools, offline sample and editing window.
- [x] Implement native menus, save dialogs, first launch and owned process cleanup.
- [x] Preserve exact dependency notices, corresponding source and build recipes.
- [x] Verify release assembly rejects incomplete, mixed or changed inputs.
- [x] Complete frozen processing and actual installation checks on all six targets.
- [ ] Publish the verified installers, source supplement and checksums.

The [desktop guide](DESKTOP.md) records installation and publisher-trust limits.
The [distribution specification](NATIVE-DISTRIBUTION.md) defines the gates;
the [assembly guide](../packaging/release/README.md) explains how release files
are tied to their actual test evidence.
