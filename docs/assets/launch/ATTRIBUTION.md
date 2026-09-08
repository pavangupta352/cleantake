# CleanTake comparison video

An 18-second edited comparison of the [published before/after WAVs](../demo/ATTRIBUTION.md), with waveforms drawn from their actual samples. It is a comparison graphic, not a recording of someone operating the app. The gap is deliberately introduced into the main microphone; the repaired passage comes from a simultaneously recorded lapel microphone.

## Credit and license

Audio: **AMI Meeting Corpus — AMI Project Consortium**, meeting **ES2004a**, channels **Headset-0** and **Lapel-0**, original meeting seconds **338–344**. Original recordings were obtained from the [University of Edinburgh AMI corpus distribution](https://groups.inf.ed.ac.uk/ami/download/) under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/), as stated on the [AMI license page](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml).

Comparison graphics and video edit: **Pavan Gupta**. The complete comparison video is shared under **CC BY 4.0**. Attribute the AMI Project Consortium and Pavan Gupta, retain the source/license links, and identify further modifications when sharing. The license includes its disclaimer of warranties and limitation of liability. No endorsement by the AMI Project Consortium or recorded participants is implied.

## What changed

The source examples were excerpted from two 20-second development fixtures. The headset was zeroed at project seconds **17–17.5**. CleanTake aligned the lapel and proposed the replacement; the demo script explicitly accepted it without changing the alignment, boundaries, gain or fade. The [source manifest](../demo/manifest.json) records that the listening WAVs were produced with **CleanTake 0.1.0**. They have not been relabeled as newly generated 0.2.0 outputs.

The video plays the six-second before clip at **1–7 seconds** and the six-second after clip at **8–14 seconds**, followed by a silent four-second end card. It adds labels and a shared-scale waveform display. No music, narration, unequal gain or loudness finishing was added. H.264/AAC encoding makes the video widely playable; AAC is lossy, so the separate PCM24 WAVs remain the reference audio. The [video manifest](manifest.json) records exact source and video hashes.

The modified recordings are controlled examples, not naturally occurring damage, participant approval or a listening-quality benchmark. Current product validation and broader limitations are recorded in [the evaluation report](../../EVALUATION.md) and [desktop validation](../../VALIDATION.md).

Corpus reference: Carletta, J. (2006). *Announcing the AMI Meeting Corpus*. The ELRA Newsletter 11(1), January–March, pp. 3–5. [Official corpus overview](https://groups.inf.ed.ac.uk/ami/corpus/overview.shtml).
