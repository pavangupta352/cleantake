# Natural-fault intake — not an evaluation result

This packet records a candidate for a separate natural-fault study. **No candidate audio has been downloaded, inspected or processed. No fault intervals, recovered words, editor sessions or listener results are claimed.** The existing [controlled evaluation](../../docs/EVALUATION.md) and its lock/results are unchanged.

## Candidate and split

The AMI publisher reports that a participant lost a lapel microphone in **ES2008a**, while the headset remained usable. This is a recorded collection problem, not a fault injected for CleanTake. The publisher note does **not** identify the participant, audio channel or event time. [AMI data problems](https://groups.inf.ed.ac.uk/ami/corpus/dataproblems.shtml).

Assign the entire **ES2008** meeting group to candidate/development intake. Keep **ES2002** reserved for a later evaluation; its audio remains uninspected. These groups differ from the already used ES2004 and IS1009 groups. A prospective split is not evidence that a usable, independently annotated evaluation set exists.

The [ES2008a directory](https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2008a/audio/) contains separate headset and lapel files for four channels. The [signal table](https://groups.inf.ed.ac.uk/ami/corpus/signals.shtml) and manual annotation metadata map speakers A–D to channels 0–3 but do not identify which lapel was lost. The inspected ES2008a word transcripts did not resolve that identity. No particular channel pair was selected by guessing.

## What is ready

[intake.json](intake.json) retains the exact candidate identity, prospective split, credit, license, official source URLs, retrieved metadata hashes and the identity of the inspected manual annotation files. Hashes identify retained metadata bytes; a later publisher revision must be recorded separately. They are **not audio hashes**. Media hashes and measured recording metadata remain absent until actual files are acquired.

AMI Meeting Corpus — **AMI Project Consortium**. The publisher licenses the corpus and annotations under [CC BY 4.0](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml), including its disclaimer of warranties. Retain credit, the [license](https://creativecommons.org/licenses/by/4.0/), source links and modification history with any redistributed excerpts. No corpus or participant endorsement is implied. No recording has been modified for this packet.

## Next execution

1. Establish the affected participant/channel and approximate time from reliable incident information or independent annotation. This is the current missing input. The available publisher note alone cannot select the relevant simultaneous files.
2. Fetch only the corresponding lapel/headset pair into a private cache. Save source URLs, download time, exact byte counts and SHA-256 **before decoding or listening**. Then record actual stream/channel, sample rate and frame count. Retain the original bytes; do not infer those measurements from the publisher's rounded directory sizes.
3. Independently annotate the natural fault, usable donor interval, surrounding speech and uncertain boundaries in original sample coordinates. Keep missed and no-usable-donor intervals. Confirm the evidence before running CleanTake, and retain every selected interval regardless of the result.
4. Freeze a separate study identity, software/settings, input/annotation hashes and comparison endpoints before processing. Do not modify the original AMI injected-fault protocol or call reused results a new study. Inspection or tuning on the reserved group requires relabeling it and reserving another group.
5. Collect actual editor and blinded listener observations separately. This candidate does not supply those people or outcomes. One microphone-loss incident also cannot establish clipping, clothing-noise, independent-device-clock or broad recovery performance.

No audio verifier was added: there are currently no selected audio inputs to verify. Once the channel mapping is established, a small acquisition/verifier can check real bytes and metadata without changing the recovery engine.
