# AMI development audio fixtures

**AMI Meeting Corpus — AMI Project Consortium.** The two 20-second excerpts are
from meeting **ES2004a**, channels **Headset-0** and **Lapel-0**, original time
**324.000–344.000 seconds**. Source URLs, original and excerpt SHA-256 hashes,
exact intervals and processing details are in [manifest.json](manifest.json).

Original recordings were obtained from the University of Edinburgh's official
[AMI corpus distribution](https://groups.inf.ed.ac.uk/ami/download/). The audio
is licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/),
as stated on the [AMI license page](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml).
The license includes its disclaimer of warranties and limitation of liability.

Changes: selected a 20-second interval and removed WAV metadata. All original
16 kHz mono PCM16 samples within that interval are preserved exactly. No gain,
resampling, denoising, generated speech, fault injection or source switching was
applied. These excerpts are development fixtures, not a held-out evaluation.

CleanTake and these modifications are not endorsed by the AMI Project Consortium
or the recorded participants. Carry this attribution, source identifiers,
modification history and license link when redistributing the fixtures.

Corpus reference: Carletta, J. (2006). *Announcing the AMI Meeting Corpus*.
The ELRA Newsletter 11(1), January–March, pp. 3–5.
[Official corpus overview](https://groups.inf.ed.ac.uk/ami/corpus/overview.shtml).

## Listening example modifications

`before.wav` and `after.wav` cover local project seconds 14 to 20 (original AMI meeting seconds 338 to 344). The headset was zeroed at local seconds 17 to 17.5. CleanTake aligned the independent lapel and proposed the repair recorded in manifest.json. That proposal was explicitly accepted by this reproducible script without manual boundary or gain adjustment. Both clips are 48 kHz mono PCM24; the primary outside the repair is preserved before PCM24 rounding. There is no loudness finishing. Source-map.json covers the full 20-second project, so add 14 seconds to a listening-clip position. These modified recordings retain the CC BY 4.0 license above.
