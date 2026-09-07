"""Public numeric contracts. All bounds use the primary's sample clock."""

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Alignment:
    offset_seconds: float = 0.0
    drift_ppm: float = 0.0
    confidence: float = 0.0
    anchors: int = 0
    residual_ms: float = 0.0
    status: str = "uncertain"
    polarity: int = 1


@dataclass(frozen=True)
class CandidateTrack:
    source_id: str
    samples: np.ndarray
    alignment: Alignment


@dataclass
class RepairProposal:
    start_frame: int
    end_frame: int
    kind: str
    source_id: str | None
    confidence: float
    reason: str
    alternatives: list[dict] = field(default_factory=list)
    status: str = "proposed"
    gain_db: float = 0.0
    fade_ms: float = 12.0
