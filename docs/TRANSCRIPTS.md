# Transcript integration

CleanTake accepts transcript text through a guarded adapter around
`turnchunk==0.4.1`:

```python
from cleantake.transcripts import import_transcript

record = import_transcript(
    transcript_text,
    source_id="source-id-from-the-project",
    filename="captions.vtt",
)
```

The adapter returns a plain JSON-safe dictionary with an ID, source ID, detected
format, unchanged input text, parsed turns, raw word records, and warnings.
Turn and word times are integer milliseconds or `null`. `time_estimated` is
true only when the input explicitly marks the timing as estimated. Missing
times remain missing.

## Formats and units

VTT, SRT, supported speech-to-text vendor JSON, and plain text use
`turnchunk`'s parsers. Recognized vendor units remain authoritative. For
example, Whisper uses seconds and AssemblyAI uses milliseconds even if the
caller passes `time_unit`.

Generic JSON must either name its fields `start_ms` and `end_ms`, or declare
the unit for generic `start` and `end` fields:

```python
record = import_transcript(
    '[{"start": 1.0, "end": 2.0, "text": "Hello"}]',
    source_id="source-a",
    filename="captions.json",
    time_unit="seconds",
)
```

This guard avoids a known `turnchunk` 0.4.1 behavior that can interpret
explicit millisecond values by magnitude. CleanTake validates generic values
before giving normalized content to the real parser. The same guard applies
when explicit millisecond fields appear inside a vendor-shaped `segments` or
`utterances` envelope.

## Provenance and limits

When JSON includes a `words` array, every word record keeps its untouched raw
object and a path back to its location in the input. Normalized timing is a
convenience for navigation; the raw vendor fields remain the provenance record.
JSON token layouts that do not use a `words` array are parsed into turns by
`turnchunk` but are not duplicated into CleanTake's `words` list.

Transcript timing does not align sources and never supplies repair boundaries.
The adapter does not invent missing end times, interpolate word timing, infer
estimated status, sanitize text into markup, or transcribe audio. Interfaces
must render imported text as text. Invalid, negative, reversed, non-finite, or
out-of-range timing raises a validation error instead of being coerced.
Distinct subtitle cues are retained even when their text repeats. Transcript
IDs include the normalized timing interpretation, so the same generic input
imported as seconds and milliseconds produces different records.

Anonymous example inputs are available in
[`examples/transcripts`](../examples/transcripts/).
