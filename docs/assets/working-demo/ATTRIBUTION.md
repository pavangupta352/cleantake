# CleanTake working demo

A recording of the actual CleanTake 0.2.1 studio comparing a deliberately damaged main microphone, accepting a replacement from the simultaneous lapel recording, and preparing and downloading a real audio export. The [silent GIF](cleantake-workflow.gif) condenses the workflow to ten seconds. The [22-second video with sound](cleantake-workflow.mp4) retains both six-second listening passes.

## Credit and license

Audio: **AMI Meeting Corpus — AMI Project Consortium**, meeting **ES2004a**, channels **Headset-0** and **Lapel-0**. Original recordings were obtained from the [University of Edinburgh AMI corpus distribution](https://groups.inf.ed.ac.uk/ami/download/) under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/), as stated on the [official AMI license page](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml).

App recording, editorial captions and video edit: **Pavan Gupta**. The GIF, video, posters and modified audio excerpts in this folder are shared under **CC BY 4.0**. Credit the AMI Project Consortium and Pavan Gupta, retain these source/license links, and identify further changes when redistributing them. The license includes its disclaimer of warranties and limitation of liability. No endorsement by the AMI Project Consortium or recorded participants is implied. CleanTake application code keeps its MIT license.

## Source and deliberate modifications

The included sample uses original meeting seconds **324–344**. Its headset recording is deliberately set to zero at project seconds **17–17.5**, corresponding to meeting seconds **341–341.5**. The lapel recording is unchanged. The sample was created in a separate local workspace using released source [0730f04](https://github.com/pavangupta352/cleantake/commit/0730f04b06f597ffcf170803a7aace359b579152).

Both listening passes cover project seconds **14–20**, or meeting seconds **338–344**. [Before](before.wav) is the actual player response for Original mode; [after](after.wav) is the actual player response after accepting the lapel proposal. Both are six-second mono, 48 kHz FLOAT WAVs. The repaired excerpt matches the corresponding six seconds of the WAV downloaded from the app exactly. No mastering or additional comparison gain was applied. The [source map](source-map.json) describes the entire 20-second exported project, including the donor, alignment, gain, crossfade and output hash; only its six-second listening excerpts are included here.

The exact repair spans frames **816039–839953**, with a **12 ms** crossfade and the proposal's original gain of approximately **12.8244 dB**. All **936,086** output frames outside that accepted interval remain identical to the primary working audio. These are observed properties of this controlled example, not a claim of natural-failure coverage, listener preference or time savings.

## How the screen recording was edited

All interface regions come from captured pixels of the real working studio. Captions identify the current step; crops make the waveform, acceptance control and export list easier to read. The pointer uses the measured coordinates of actual clicks. No interface controls, waveform data, repair results or export files were invented. The settled opening frame is briefly held, and the video ends after the actual download, before the export panel closes.

Screen frames were sampled about twelve times per second and presented at 30 fps in the MP4. Its audio comes from those same project revisions and is placed at the app's recorded Web Audio scheduling times. The visible playhead retains the app's normal update cadence. H.264/AAC encoding is lossy; the separate WAV files are the audio references. No music, narration, voice generation or unequal before/after amplification was added.

The GIF is silent and deliberately condensed, including accelerated listening passages; it cannot establish an audible improvement or how long a new user's task would take. Its link leads to the sound-on version. `still.png` is the static README alternative, and `poster.png` is the video poster. File hashes, timing and provenance are in [the media manifest](manifest.json).

The earlier [18-second comparison](../launch/cleantake-comparison.mp4) and [0.1.0 audio provenance](../demo/ATTRIBUTION.md) remain unchanged. This folder contains fresh 0.2.1 player responses and capture evidence; it does not relabel the old WAVs.

Corpus reference: Carletta, J. (2006). *Announcing the AMI Meeting Corpus*. The ELRA Newsletter 11(1), January–March, pp. 3–5. [Official corpus overview](https://groups.inf.ed.ac.uk/ami/corpus/overview.shtml).
