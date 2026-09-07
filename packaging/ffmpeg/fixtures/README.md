# Numerical decoder fixture

`tone.mp3` is one second of a procedural 440 Hz sine wave, with no speech or
third-party recording. `manifest.json` records the PCM formula, generating
FFmpeg version, encoder and exact encoded-file hash. The signal is mono, 44.1 kHz,
signed 16-bit PCM before encoding. Encode with `-map_metadata -1 -c:a libmp3lame`.

This numerical fixture is dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

The build validator uses the fixed MP3 to exercise the built-in decoder without
requiring an MP3 encoder in the distributed tools. Other format probes generate
their own numerical PCM at build time using the built-in encoders.
