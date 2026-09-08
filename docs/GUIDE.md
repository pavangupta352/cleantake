# Recover a passage

Start with two to four recordings of the same event: a main microphone plus
camera audio, a recorder, a lapel, or another microphone that heard the speaker.
Different takes of the same sentence will not have the same timing.

## Import and align

1. Run `cleantake studio` and create a project. Import the recording you want to
   preserve first; it becomes the primary timeline.
2. Add the alternate recordings. Give sources names you can distinguish while
   listening. For multichannel files, choose the channel or mono downmix you need.
3. Run analysis. Sources with enough matching evidence show an alignment. A
   source marked uncertain keeps its own clock and cannot supply an accepted
   repair until you set a usable alignment.

Offset and clock drift are different. Offset corrects the start time. Drift
corrects a gradually increasing difference during a long recording. Manual
alignment uses seconds and parts per million. A positive offset means the same
sound occurs later in the alternate file. Check near both the beginning and end
when setting drift. Changing the primary source changes the reference timeline
and requires confirmation because existing timing decisions must be reset.

## Compare at the same moment

Select a proposed repair to see its range, donor, score and reason. Use
**Original**, **Repair** and **Source** to compare at the same timeline position.
Source playback helps you hear the alternate's room sound before deciding.
The score describes the available evidence; it is not a listening-quality
probability or a recommendation to accept without listening.

The timeline supports zoom, pan, fit and numeric seek. The playhead and every
aligned lane share one ruler. Space starts or stops playback when you are not
typing. Visible numeric controls provide an alternative to waveform interaction.
Audio streams in bounded windows. If playback cannot keep up, it stops at the
last heard boundary instead of skipping unheard material.

## Make the repair yours

Adjust the start and end, choose the donor, match its level with gain and set the
crossfade. Listen to the whole phrase, including its entry and exit. Accept the
repair when it works, or reject it. An unaccepted suggestion leaves the primary
unchanged in the export.

Before accepting, check **Replacement details** directly above the decision. It
shows the saved recording name, the original filename when different, and the
passage in both project and recording time. Recording time includes the saved
offset and drift; displayed times round to milliseconds. The source map retains
the frame coordinates and crossfade contributors.

When you edit the fields, the disclosure keeps showing the saved values until
you choose **Save passage changes**. Missing alignment or incomplete coverage
is explained here, and Accept stays unavailable until the saved source covers
the passage.

If a problem has no useful suggestion, create a manual repair over its time
range and select an aligned source. CleanTake rejects accepted edits with
overlapping ranges, unavailable donor coverage or gain that would exceed full
scale. Reduce gain, move the bounds or choose another source instead of hiding
the conflict.

All repair edits save as project revisions and can be undone and redone. Source
recordings stay unchanged. A transcript can help you find a phrase; its timing
is navigation context and never silently determines an audio edit. Estimated
timestamps remain labeled. See [supported transcript formats](TRANSCRIPTS.md).

## Export and hand off

Export accepted repairs as a float WAV or PCM24 FLAC. Every export also contains
aligned stems, an editable Reaper session and a JSON map of source contributors,
including both sides of a crossfade. Optional loudness finishing creates a
separate output and reports its measured result; the unmastered mix remains.

A portable project archive includes original recordings and decisions. Importing
it creates a new project so it cannot overwrite an existing one. Export the
archive when moving work between computers or preserving a complete session.

The [export guide](EXPORTS.md) explains sample formats, exact source-map semantics,
finishing and the measured Reaper interoperability check.

## What to expect

Automatic proposals are conservative and can miss damaged passages. Distant
microphones, different room responses, heavy clipping, edits inside a source or
weak shared speech can make synchronization uncertain. A replacement can also
change tone or room sound even when its timing is right. Listen and adjust.

CleanTake recovers audio that another source recorded. When every recording
lost a word, there is no recorded replacement. It leaves those cases unresolved.
It does not remove silence, overlaps, laughter or fillers automatically. The
[evaluation report](EVALUATION.md) records tested cases and failures; independent
listening preference and editor-time advantage have not been measured.
