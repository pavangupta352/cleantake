"""Pure numerical recording synchronization and source-based repair."""

from .alignment import estimate_alignment, sample_aligned
from .contracts import Alignment, CandidateTrack, RepairProposal
from .detection import find_repairs
from .render import contributor_spans, render_range

__all__ = [
    "Alignment",
    "CandidateTrack",
    "RepairProposal",
    "estimate_alignment",
    "sample_aligned",
    "find_repairs",
    "render_range",
    "contributor_spans",
]
