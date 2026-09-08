# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Local Python audio processing, a React and TypeScript studio served on loopback, and a command-line interface. Version 0.2.0 includes an Electron desktop window with a frozen Python runtime and bundled media tools, so supported native installations do not require separate developer runtimes. The processing engine is shared across desktop, browser and CLI clients. See the [desktop guide](docs/DESKTOP.md) for supported systems and installation steps.

## Users

Interview editors, podcasters, filmmakers and course creators with simultaneous recordings from a main microphone and one or more backups.

## Product Purpose

Recover damaged dialogue from the recordings you already have. Make the actual recorded replacement easy to find, hear, inspect, accept and revise, then deliver finished dialogue and editable source decisions.

## Positioning

A source-traceable dialogue rescue workflow. Every repair uses an identifiable passage from a supplied recording. Alignment and mastering are established capabilities; CleanTake's proposed advantage must be earned by completing recovery and review with less work.

## Operating Context

An editor works on a computer with headphones, comparing multiple recordings of the same performance. Original media stays on that computer. A studio project retains imported sources, timing transforms, proposed and accepted repairs, transcript context and export settings across sessions.

## Capabilities and Constraints

The released workflow covers two to four simultaneous tracks, audio and video ingestion, offset and drift synchronization, conservative damage suggestions, manual repair ranges and source selection, contextual listening, undo and redo, level matching and crossfades, finished audio and editable exports. The [validation record](docs/VALIDATION.md) identifies the tested revisions, platforms and acceptance results.

No account, cloud processing, paid API or model download is required for core recovery. Never invent missing speech. Preserve timing, interruptions, overlapping voices, breaths and laughter. Do not auto-delete silence or filler words. Mark uncertain synchronization and unrepairable damage explicitly. Transcript imports assist navigation and speaker labels; they never authorize audio cuts.

## Brand Commitments

CleanTake is the selected working product name. Maintained by Pavan Gupta. Plain, precise language; audible and inspectable evidence before claims. No invented performance figures, endorsements or star forecasts.

## Evidence on Hand

Dated research and source reviews informed the implementation. The completed [evaluation](docs/EVALUATION.md) uses licensed simultaneous AMI recordings with explicitly injected damage, reserved evaluation spans and a separate 30-minute resource check. It records exact rendering, recovered and missed intervals, uncertain alignments and unrequested flags. These controlled results and generated numerical fixtures support engineering claims; they do not establish organic-damage recovery, independent listening preference or editor-time savings.

## Product Principles

1. Recover the recorded performance; preserve the original.
2. Make every source switch visible, audible and reversible.
3. Expose uncertainty before an editor commits a repair.
4. Finish the whole path from import to portable export.
5. Keep the core useful and installable independently.

## Accessibility & Inclusion

Keyboard operation, visible focus, labeled controls and status announcements. Never encode repair status only by color. Waveform actions also have numeric time controls. Listening controls respect the user's playback choice and reduced-motion preference.

## Desktop installation requirement

Ship self-contained native packages for supported Windows, macOS and Linux
systems. Include application runtimes, browser engine, media tools, offline
sample and licenses. Use native install/open/quit behavior, preserve projects
across updates and uninstalls, and verify each shipped architecture. System
support and publisher-signing prompts must be described from actual evidence;
do not claim that every historical PC or operating system is supported.
