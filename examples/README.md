# Try a recovery

The installed package contains a 20-second recording from two real microphones.
Create its sample project and open the studio:

```sh
cleantake demo
cleantake studio
```

Open **Sample · recover a missing half-second**. At 17 seconds, the headset has
an injected half-second gap. The lapel recorded the same speech. Analysis creates
a proposal; compare the original, repair and lapel at the same point, then accept
or adjust it. The confidence shown is an evidence score, not a probability of
good listening quality. Nothing is accepted automatically by `demo`.

The voices come from the AMI Meeting Corpus, meeting ES2004a, original interval
324 to 344 seconds. The headset and lapel are distinct recordings. This example
uses controlled damage on development audio. It does not demonstrate recovery
from every kind of recording failure. See the bundled
[attribution](../src/cleantake/assets/demo/ATTRIBUTION.md) and
[source hashes](../src/cleantake/assets/demo/manifest.json).

## Import the sample yourself

From a source checkout:

```sh
uv run python scripts/prepare_demo.py --output sample-recordings
uv run cleantake studio
```

Create a project and import `Headset-injected-dropout.wav` first, then
`Lapel-backup.wav`. The new directory also contains the unchanged headset,
attribution and a manifest naming every modification. The command refuses to
overwrite an existing directory.

## Numerical clock fixture

```sh
uv run python scripts/generate_fixture.py --output clock-fixture
uv run cleantake repair clock-fixture/primary.wav clock-fixture/backup.wav \
  --output clock-review
```

This is filtered deterministic noise, not human speech. Its manifest records a
375 ms offset, 120 ppm clock drift and a half-second gap. The default command
retains proposals for review. Explicit `--accept-confident` enables automatic
acceptance at the chosen evidence score; listen before using the result.

## Transcript examples

[Transcript integration](../docs/TRANSCRIPTS.md) explains the real turnchunk
adapter. Files in [transcripts](transcripts/) show timestamped navigation. A
transcript never supplies replacement speech or changes audio edit boundaries.
