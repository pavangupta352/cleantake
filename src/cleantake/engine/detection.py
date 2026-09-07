"""Conservative overload/dropout evidence; no inferred noise superiority.

A dropout requires near-zero primary PCM, audible donor signal throughout the
interval, and correlated intact context. Shared silence therefore stays untouched.
Overload without an intact, contextual donor remains an unresolved review item.
"""

import numpy as np

from .alignment import _array, _finite, _rate, _transform, sample_aligned
from .contracts import RepairProposal


def _stats(samples, width):
    count = len(samples) // width
    if not count:
        return np.empty(0), np.empty(0), np.empty(0, dtype=bool)
    frames = np.asarray(samples[: count * width], dtype=np.float64).reshape(count, width)
    absolute = np.abs(frames)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    peak = np.max(absolute, axis=1)
    # Three identical high-level samples identify actual flat-topped PCM, even
    # if a clipped recording was subsequently attenuated below digital full scale.
    flat = (np.abs(np.diff(frames, axis=1)) < 1e-8) & (absolute[:, 1:] > 0.05)
    plateau = np.mean(flat[:, :-1] & flat[:, 1:], axis=1) > 0.01
    overload = np.mean(absolute >= 0.999, axis=1) >= 0.01
    return rms, peak, plateau | overload


def _covered(candidate, start, end, rate):
    scale = _transform(candidate.alignment)
    first = start * scale + candidate.alignment.offset_seconds * rate
    last = (end - 1) * scale + candidate.alignment.offset_seconds * rate
    return end > start and first >= 0 and last <= len(candidate.samples) - 1


def _context(reference, candidate, start, end, rate, width):
    pairs = []
    for lo, hi in ((max(0, start - rate), start), (end, min(len(reference), end + rate))):
        hi = lo + (hi - lo) // width * width
        if hi <= lo or not _covered(candidate, lo, hi, rate):
            continue
        primary = reference[lo:hi]
        donor = sample_aligned(candidate.samples, lo, hi, rate, candidate.alignment)
        prms, _, pclip = _stats(primary, width)
        drms, _, dclip = _stats(donor, width)
        use = (prms > 0.002) & (drms > 1e-6) & ~pclip & ~dclip
        if use.any():
            pairs.append(
                (primary.reshape(-1, width)[use].ravel(), donor.reshape(-1, width)[use].ravel())
            )
    if not pairs or sum(len(p) for p, _ in pairs) < rate * 0.1:
        return None
    p = np.concatenate([p for p, _ in pairs])
    d = np.concatenate([d for _, d in pairs])
    p = p - p.mean()
    d = d - d.mean()
    ppower, dpower = np.dot(p, p), np.dot(d, d)
    corr = float(np.dot(p, d) / max(1e-16, np.sqrt(ppower * dpower)))
    gain_db = float(10 * np.log10(max(ppower, 1e-16) / max(dpower, 1e-16)))
    if corr < 0.65 or abs(gain_db) > 24:
        return None
    return corr, gain_db


def _signal_above_background(candidate, start, end, rate, width, reference_frames):
    """Require varying recorded energy above a local low-energy baseline.

    A correlated surrounding conversation does not establish speech in a gap.
    Compare the interval's 80th-percentile frame RMS with the 10th percentile of
    the interval and up to one second of context on either side. Require 6 dB
    of excess; stationary room noise stays at its baseline regardless of gain.
    The baseline is conservative evidence, not a calibrated speech classifier:
    steady unvoiced material or no distinguishable background stays unproposed.
    Fixed logarithmic histograms keep working state independent of gap length.
    """
    edges = np.geomspace(1e-12, 1e3, 601)
    local_hist = np.zeros(600, dtype=np.int64)
    interval_hist = np.zeros(600, dtype=np.int64)
    for left, right, in_interval in (
        (max(0, start - rate), start, False),
        (start, end, True),
        (end, min(reference_frames, end + rate), False),
    ):
        # Outside the primary, only genuinely available donor samples may
        # establish the background; uncovered zero padding is not evidence.
        scale = _transform(candidate.alignment)
        last_available = (
            int(
                np.floor(
                    (len(candidate.samples) - 1 - candidate.alignment.offset_seconds * rate) / scale
                )
            )
            + 1
        )
        first_available = int(np.ceil(-candidate.alignment.offset_seconds * rate / scale))
        left, right = max(left, first_available, 0), min(right, last_available)
        right = left + max(0, right - left) // width * width
        for lo in range(left, right, width * 500):
            hi = min(right, lo + width * 500)
            pcm = sample_aligned(candidate.samples, lo, hi, rate, candidate.alignment)
            rms, _, _ = _stats(pcm, width)
            histogram = np.histogram(np.clip(rms, edges[0], edges[-1]), bins=edges)[0]
            local_hist += histogram
            if in_interval:
                interval_hist += histogram
    if not interval_hist.sum() or not local_hist.sum():
        return False
    floor_bin = min(599, int(np.searchsorted(np.cumsum(local_hist), local_hist.sum() * 0.1)))
    signal_bin = min(599, int(np.searchsorted(np.cumsum(interval_hist), interval_hist.sum() * 0.8)))
    # Upper floor bound and lower signal bound err against a false recovery.
    return edges[signal_bin] >= 2 * edges[floor_bin + 1]


def _proposal(reference, candidates, start, end, kind, rate, width):
    if end - start < width * 2:
        return None
    alternatives = []
    for candidate in candidates:
        if candidate.alignment.status not in {"aligned", "manual", "reference"}:
            continue
        if not _covered(candidate, start, end, rate):
            continue
        context = _context(reference, candidate, start, end, rate, width)
        if context is None:
            continue
        corr, gain = context
        if kind == "dropout" and not _signal_above_background(
            candidate, start, end, rate, width, len(reference)
        ):
            continue
        valid, maximum = True, 0.0
        for lo in range(start, end, width * 500):
            hi = min(end, lo + width * 500)
            donor = sample_aligned(candidate.samples, lo, hi, rate, candidate.alignment)
            rms, peaks, clipping = _stats(donor, width)
            if clipping.any() or not len(rms) or np.any(rms * 10 ** (gain / 20) < 0.001):
                valid = False
                break
            maximum = max(maximum, float(np.max(peaks)))
        if not valid:
            continue
        # A bounded matched gain may need attenuation to keep the donor below full scale.
        gain = min(gain, float(20 * np.log10(0.98 / max(maximum, 1e-12))))
        if gain < -24:
            continue
        alignment_confidence = (
            1.0
            if candidate.alignment.status in {"manual", "reference"}
            else candidate.alignment.confidence
        )
        confidence = float(np.clip(corr * alignment_confidence, 0, 0.98))
        alternatives.append(
            {
                "source_id": candidate.source_id,
                "confidence": confidence,
                "gain_db": gain,
                "reason": "Intact interval with correlated surrounding signal",
            }
        )
    alternatives.sort(key=lambda item: (-item["confidence"], item["source_id"]))
    if not alternatives:
        if kind == "dropout":
            return None  # No evidence distinguishing all-source silence from missing speech.
        return RepairProposal(
            start,
            end,
            kind,
            None,
            0.0,
            "Overload evidence; no verified intact donor",
            status="unresolved",
        )
    best = alternatives[0]
    return RepairProposal(
        start,
        end,
        kind,
        best["source_id"],
        best["confidence"],
        "Missing primary signal" if kind == "dropout" else "Flat-top overload",
        alternatives=alternatives,
        gain_db=best["gain_db"],
    )


def find_repairs(reference, candidates, sample_rate):
    """Suggest frame-aligned repairs for review, never automatically accept them.

    Uses 20 ms evidence windows and ten-second PCM blocks. Proposal boundaries
    have this resolution. Weak/noisy context and all-source silence are not enough
    to assert recoverability. No noise-only replacements are currently proposed.
    """
    _array(reference)
    _rate(sample_rate)
    _finite(reference)
    candidates = list(candidates)
    ids = [c.source_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate candidate source IDs")
    for candidate in candidates:
        _array(candidate.samples)
        _finite(candidate.samples)
        _transform(candidate.alignment)
    width = max(4, round(sample_rate * 0.020))
    proposals = []
    active, begin = 0, 0
    stop = len(reference) // width * width
    for block_start in range(0, stop, width * 500):
        block = reference[block_start : min(stop, block_start + width * 500)]
        _, peak, clip = _stats(block, width)
        labels = np.where(clip, 2, np.where(peak <= 1e-7, 1, 0))
        for index, label in enumerate(labels):
            frame = block_start + index * width
            if label != active:
                if active:
                    result = _proposal(
                        reference,
                        candidates,
                        begin,
                        frame,
                        "dropout" if active == 1 else "clipping",
                        sample_rate,
                        width,
                    )
                    if result:
                        proposals.append(result)
                active, begin = label, frame
    if active:
        result = _proposal(
            reference,
            candidates,
            begin,
            stop,
            "dropout" if active == 1 else "clipping",
            sample_rate,
            width,
        )
        if result:
            proposals.append(result)
    return proposals
