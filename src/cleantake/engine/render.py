"""Deterministic accepted-edit rendering and explicit source-map contributors."""

import math

import numpy as np

from .alignment import _array, _bounds, _finite, _rate, _transform, sample_aligned
from .contracts import Alignment
from .detection import _covered


def _decisions(reference, candidates, repairs, start, end, rate):
    _array(reference)
    _rate(rate)
    _bounds(start, end)
    if end > len(reference):
        raise ValueError("Requested range exceeds primary duration")
    by_id = {}
    for candidate in candidates:
        _array(candidate.samples)
        if candidate.source_id in by_id:
            raise ValueError("Duplicate candidate source IDs")
        by_id[candidate.source_id] = candidate
    accepted = [repair for repair in repairs if repair.status == "accepted"]
    # Validate before sorting so malformed mixed bound types get a useful error.
    for repair in accepted:
        _bounds(repair.start_frame, repair.end_frame)
        if repair.end_frame <= repair.start_frame or repair.end_frame > len(reference):
            raise ValueError("Accepted repair exceeds primary duration or is empty")
        if repair.source_id not in by_id:
            raise ValueError("Accepted repair references unknown source")
        candidate = by_id[repair.source_id]
        if candidate.alignment.status not in {"aligned", "manual", "reference"}:
            raise ValueError("Accepted repair requires verified or manual alignment")
        if not _covered(candidate, repair.start_frame, repair.end_frame, rate):
            raise ValueError("Accepted repair exceeds donor coverage")
        if not np.isfinite([repair.gain_db, repair.fade_ms]).all():
            raise ValueError("Repair gain and fade must be finite")
        if not -24 <= repair.gain_db <= 24 or not 0 <= repair.fade_ms <= 1000:
            raise ValueError("Repair gain must be within ±24 dB and fade within 0–1000 ms")
    accepted.sort(key=lambda repair: repair.start_frame)
    for left, right in zip(accepted, accepted[1:], strict=False):
        if left.end_frame > right.start_frame:
            raise ValueError("Accepted repairs overlap")
    return by_id, accepted


def _fade_frames(repair, rate):
    return min(round(repair.fade_ms * rate / 1000), (repair.end_frame - repair.start_frame) // 2)


def _weight(frames, repair, rate):
    fade = _fade_frames(repair, rate)
    if not fade:
        return np.ones(np.shape(frames), dtype=np.float64)
    return np.minimum(
        1.0,
        np.minimum(
            (frames - repair.start_frame + 1) / (fade + 1), (repair.end_frame - frames) / (fade + 1)
        ),
    )


def render_range(reference, candidates, repairs, start_frame, end_frame, sample_rate):
    """Render primary-clock [start,end), using only accepted recorded donors.

    Crossfades are convex linear blends wholly inside each accepted interval.
    Weights depend on absolute frames, so arbitrary chunks are sample-identical.
    Gain outside ±24 dB, unavailable donor coverage and donor sample peaks over
    full scale raise ValueError; no clipping/limiting or hidden finishing occurs.
    Requested-range allocation is intentional; callers stream long exports.
    """
    by_id, accepted = _decisions(
        reference, candidates, repairs, start_frame, end_frame, sample_rate
    )
    output = np.array(reference[start_frame:end_frame], dtype=np.float64, copy=True)
    _finite(output)
    for repair in accepted:
        lo, hi = max(start_frame, repair.start_frame), min(end_frame, repair.end_frame)
        if lo >= hi:
            continue
        donor = by_id[repair.source_id]
        pcm = sample_aligned(donor.samples, lo, hi, sample_rate, donor.alignment)
        pcm *= 10 ** (repair.gain_db / 20)
        if np.any(np.abs(pcm) > 1.0 + 1e-12):
            raise ValueError("Donor gain would exceed full scale; lower the repair gain")
        weights = _weight(np.arange(lo, hi, dtype=np.int64), repair, sample_rate)
        section = output[lo - start_frame : hi - start_frame]
        section[:] = section * (1 - weights) + pcm * weights
    return output


def _contributor(
    source_id, start, end, alignment, gain, first_weight, last_weight, rate, primary=False
):
    scale = _transform(alignment)
    first = start * scale + alignment.offset_seconds * rate
    exclusive = end * scale + alignment.offset_seconds * rate
    last = (end - 1) * scale + alignment.offset_seconds * rate
    return {
        "source_id": source_id,
        "source_start_frame": float(first),
        "source_end_frame": float(exclusive),
        "read_start_frame": math.floor(first),
        "read_end_frame": math.ceil(last) + 1,
        "gain_db": float(gain),
        "alignment": {
            "offset_seconds": alignment.offset_seconds,
            "drift_ppm": alignment.drift_ppm,
            "polarity": alignment.polarity,
        },
        "interpolation": "none" if primary else "linear",
        "weight": {
            "curve": "constant" if first_weight == last_weight else "linear",
            "start": float(first_weight),
            "end": float(last_weight),
        },
    }


def contributor_spans(
    reference,
    candidates,
    repairs,
    start_frame,
    end_frame,
    sample_rate,
    *,
    primary_source_id="primary",
):
    """Describe all contributors to [start,end), independent of chunk size.

    Each span contains start_frame/end_frame and contributor records: source_id,
    source_start_frame/source_end_frame (continuous, exclusive clock mapping),
    read_start_frame/read_end_frame (integer interpolation support), gain_db,
    alignment, interpolation and weight. Weight start/end are the first and last
    INCLUDED sample weights, linearly interpolated between those frames. Both
    contributors appear in every seam. This records the unmastered render;
    exporters must separately record hashes, versions and downstream processing.
    """
    by_id, accepted = _decisions(
        reference, candidates, repairs, start_frame, end_frame, sample_rate
    )
    points = {start_frame, end_frame}
    for repair in accepted:
        fade = _fade_frames(repair, sample_rate)
        points.update(
            point
            for point in (
                repair.start_frame,
                repair.start_frame + fade,
                repair.end_frame - fade,
                repair.end_frame,
            )
            if start_frame < point < end_frame
        )
    bounds = sorted(points)
    result = []
    edit_index = 0
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        while edit_index < len(accepted) and accepted[edit_index].end_frame <= lo:
            edit_index += 1
        repair = accepted[edit_index] if edit_index < len(accepted) else None
        if repair is None or repair.start_frame > lo:
            contributors = [
                _contributor(primary_source_id, lo, hi, Alignment(), 0, 1, 1, sample_rate, True)
            ]
        else:
            weights = _weight(np.array([lo, hi - 1]), repair, sample_rate)
            contributors = []
            if min(weights) < 1:
                contributors.append(
                    _contributor(
                        primary_source_id,
                        lo,
                        hi,
                        Alignment(),
                        0,
                        1 - weights[0],
                        1 - weights[1],
                        sample_rate,
                        True,
                    )
                )
            donor = by_id[repair.source_id]
            contribution = _contributor(
                donor.source_id,
                lo,
                hi,
                donor.alignment,
                repair.gain_db,
                weights[0],
                weights[1],
                sample_rate,
            )
            contributors.append(contribution)
        result.append({"start_frame": lo, "end_frame": hi, "contributors": contributors})
    return result
