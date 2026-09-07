"""Prepare labeled controlled damage on the licensed distinct-microphone fixture."""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

source = Path(__file__).resolve().parents[2] / "tests" / "engine" / "data"
destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
audio, rate = sf.read(source / "ES2004a_0324-0344_Headset-0.wav")
# 341.0–341.5 seconds in the original AMI meeting is locally 17.0–17.5 s.
audio[17 * rate : int(17.5 * rate)] = 0
sf.write(destination / "Headset-injected-dropout.wav", audio, rate, subtype="PCM_24")
rng = np.random.default_rng(771)
sf.write(destination / "Unrelated-noise.wav", rng.normal(0, 0.015, len(audio)), rate)
(destination / "invalid.wav").write_text("This file is deliberately not audio.")

lapel_audio, lapel_rate = sf.read(source / "ES2004a_0324-0344_Lapel-0.wav")
sf.write(destination / "Lapel-identity-probe.wav", lapel_audio * 0.5, lapel_rate, subtype="PCM_24")
