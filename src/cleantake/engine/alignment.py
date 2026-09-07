"""Bounded-window correlation and robust affine recording-clock estimation.

The candidate clock is reference_frame * (1 + drift_ppm / 1e6) +
offset_seconds * sample_rate. Correlation requires shared, non-periodic signal;
uncorrelated microphones, repeats and sparse coverage can remain uncertain.
"""

import heapq
from math import gcd

import numpy as np
from scipy.signal import correlate, resample_poly
from scipy.stats import theilslopes

from .contracts import Alignment


def _array(samples):
    if not isinstance(samples, np.ndarray) or samples.ndim != 1:
        raise ValueError("PCM must be a one-dimensional NumPy array")
    if not np.issubdtype(samples.dtype, np.floating):
        raise ValueError("PCM must contain floating point samples")


def _rate(rate):
    if isinstance(rate, bool) or not isinstance(rate, (int, np.integer)) or rate <= 0:
        raise ValueError("sample_rate must be a positive integer")


def _finite(samples):
    for start in range(0, len(samples), 262144):
        if not np.isfinite(samples[start : start + 262144]).all():
            raise ValueError("PCM contains non-finite samples")


def _transform(alignment):
    scale = 1 + alignment.drift_ppm / 1e6
    if not np.isfinite([scale, alignment.offset_seconds]).all() or scale <= 0:
        raise ValueError("Invalid alignment clock")
    if alignment.polarity not in (-1, 1):
        raise ValueError("Alignment polarity must be +1 or -1")
    return scale


def _bounds(start, end):
    if any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) for x in (start, end)):
        raise ValueError("Frame bounds must be integers")
    if start < 0 or end < start:
        raise ValueError("Invalid frame bounds")


def sample_aligned(candidate, start_frame, end_frame, sample_rate, alignment):
    """Return linearly interpolated, polarity-correct PCM; uncovered frames are zero.

    Allocation is proportional to the requested range, never the recording size.
    Rendering accepted edits additionally rejects missing donor coverage.
    """
    _array(candidate)
    _rate(sample_rate)
    _bounds(start_frame, end_frame)
    scale = _transform(alignment)
    positions = np.arange(start_frame, end_frame, dtype=np.float64) * scale
    positions += alignment.offset_seconds * sample_rate
    out = np.zeros(len(positions), dtype=np.float64)
    mask = (positions >= 0) & (positions <= len(candidate) - 1)
    if mask.any():
        pos = positions[mask]
        lower = np.floor(pos).astype(np.int64)
        upper = np.ceil(pos).astype(np.int64)
        a = np.asarray(candidate[lower], dtype=np.float64)
        b = np.asarray(candidate[upper], dtype=np.float64)
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("PCM contains non-finite samples")
        out[mask] = (a + (b - a) * (pos - lower)) * alignment.polarity
    return out


def _resample(samples, rate, target):
    divisor = gcd(rate, target)
    return resample_poly(np.asarray(samples, dtype=np.float64), target // divisor, rate // divisor)


def _correlations(template, signal):
    """Pearson coefficient at each complete template position, with bounded vectors."""
    template = template - template.mean()
    norm = np.dot(template, template)
    if norm < len(template) * 1e-12 or len(signal) < len(template):
        return np.empty(0)
    sums = np.concatenate(([0.0], np.cumsum(signal)))
    squares = np.concatenate(([0.0], np.cumsum(signal * signal)))
    n = len(template)
    variance = squares[n:] - squares[:-n] - (sums[n:] - sums[:-n]) ** 2 / n
    numerator = correlate(signal, template, mode="valid", method="fft")
    return numerator / np.sqrt(np.maximum(variance * norm, 1e-24))


def _peaks(correlation, rate):
    if not len(correlation):
        return []
    values = np.abs(correlation).copy()
    found = []
    for _ in range(2):
        index = int(np.argmax(values))
        found.append((index, float(correlation[index])))
        radius = max(1, int(rate * 0.012))
        values[max(0, index - radius) : index + radius + 1] = 0
    return found


def _anchor_starts(reference, rate, width):
    """Select energetic windows throughout the recording with bounded state.

    Equally spaced probes miss sparse speakers. Keep one strong window per time
    region plus a small pool of strong speech windows, without a full PCM copy.
    """
    step = max(1, width // 3)
    regions = {}
    strongest = []
    block_step = max(step, (rate * 12 // step) * step)
    last = len(reference) - width
    for lo in range(0, last + 1, block_step):
        raw = np.asarray(
            reference[lo : min(len(reference), lo + block_step + width)], dtype=np.float64
        )
        energy = np.concatenate(([0.0], np.cumsum(raw * raw)))
        for start in range(lo, min(last + 1, lo + block_step), step):
            local = start - lo
            score = float((energy[local + width] - energy[local]) / width)
            region = min(17, start * 18 // max(1, len(reference)))
            if score > regions.get(region, (-1, 0))[0]:
                regions[region] = (score, start)
            if len(strongest) < 128:
                heapq.heappush(strongest, (score, start))
            elif score > strongest[0][0]:
                heapq.heapreplace(strongest, (score, start))
    # Reserve temporal coverage before filling remaining slots with loud windows.
    # A global relative-energy cutoff would suppress a valid quiet late speaker.
    selected = []
    for score, start in sorted(regions.values(), key=lambda item: item[1]):
        if score >= 1e-12 and all(abs(start - old) >= width for old in selected):
            selected.append(start)
    for score, start in sorted(strongest, reverse=True):
        if len(selected) >= 24:
            break
        if score >= 1e-12 and all(abs(start - old) >= width for old in selected):
            selected.append(start)
    return np.asarray(sorted(selected), dtype=int)


def estimate_alignment(reference, candidate, sample_rate):
    """Estimate offset/drift from up to 24 activity-selected signal anchors.

    Searches the whole candidate in 24 s blocks at 2 kHz (bounded working RAM),
    then refines at up to 8 kHz. A robust fit needs three unique, consistent
    anchors. Silence, tonal/repeated ambiguity and weak matches stay uncertain.
    This estimates a single affine clock; cuts or changing drift require review.
    """
    _array(reference)
    _array(candidate)
    _rate(sample_rate)
    _finite(reference)
    _finite(candidate)
    if min(len(reference), len(candidate)) < sample_rate * 1.2:
        return Alignment()
    coarse_rate = min(sample_rate, 2000)
    fine_rate = min(sample_rate, 8000)
    width = max(4, int(sample_rate * 0.6))
    starts = _anchor_starts(reference, sample_rate, width)
    templates = [_resample(reference[s : s + width], sample_rate, coarse_rate) for s in starts]
    matches = [[] for _ in starts]
    step = sample_rate * 24
    for block_start in range(0, len(candidate), step):
        raw = candidate[block_start : min(len(candidate), block_start + step + width)]
        block = _resample(raw, sample_rate, coarse_rate)
        for i, template in enumerate(templates):
            corr = _correlations(template, block)
            for index, value in _peaks(corr, coarse_rate):
                matches[i].append((abs(value), block_start / sample_rate + index / coarse_rate))
    anchors = []
    for start, options in zip(starts, matches, strict=True):
        if not options:
            continue
        options.sort(reverse=True)
        score, time = options[0]
        competitor = max((s for s, t in options[1:] if abs(t - time) > 0.020), default=0)
        if score < 0.45 or competitor > score * 0.85:
            continue
        lo = max(0, round((time - 0.025) * sample_rate))
        hi = min(len(candidate), round((time + 0.625) * sample_rate))
        template = _resample(reference[start : start + width], sample_rate, fine_rate)
        corr = _correlations(template, _resample(candidate[lo:hi], sample_rate, fine_rate))
        if not len(corr):
            continue
        index = int(np.argmax(np.abs(corr)))
        value = float(corr[index])
        if abs(value) < 0.40:
            continue
        # Parabolic peak refinement avoids quantizing all clock anchors to 1/8 ms.
        delta = 0.0
        if 0 < index < len(corr) - 1:
            y = np.abs(corr[index - 1 : index + 2])
            denominator = y[0] - 2 * y[1] + y[2]
            if denominator < -1e-10:
                delta = float(np.clip(0.5 * (y[0] - y[2]) / denominator, -0.5, 0.5))
        ref_time = (start + width / 2) / sample_rate
        cand_time = lo / sample_rate + (index + delta) / fine_rate + width / sample_rate / 2
        anchors.append((ref_time, cand_time - ref_time, abs(value), 1 if value > 0 else -1))
    if len(anchors) < 3:
        return Alignment(anchors=len(anchors))
    points = np.asarray(anchors)
    polarity = 1 if np.sum(points[:, 3]) >= 0 else -1
    points = points[points[:, 3] == polarity]
    if len(points) < 3:
        return Alignment(anchors=len(points))
    slope, intercept, _, _ = theilslopes(points[:, 1], points[:, 0])
    error = np.abs(points[:, 1] - (intercept + slope * points[:, 0]))
    # A robust fit may remove an isolated weak mismatch, but coherent or strong
    # temporally coherent contradictory matches oppose a GLOBAL affine clock. Do not
    # silently grant the surviving section's confidence to the rest of a take.
    outliers = error > 0.003
    signed_error = points[:, 1] - (intercept + slope * points[:, 0])
    coherent_neighbors = (
        outliers[:-1]
        & outliers[1:]
        & (np.sign(signed_error[:-1]) == np.sign(signed_error[1:]))
        & (np.abs(np.diff(signed_error)) <= 0.003)
    )
    contradictory = np.any(coherent_neighbors) or np.any(outliers & (points[:, 2] >= 0.85))
    points = points[~outliers]
    if len(points) < 3:
        return Alignment(anchors=len(points))
    slope, intercept = np.polyfit(points[:, 0], points[:, 1], 1)
    residual = float(np.sqrt(np.mean((points[:, 1] - intercept - slope * points[:, 0]) ** 2)))
    confidence = float(np.clip(np.median(points[:, 2]) * min(1, len(points) / 5), 0, 1))
    span = float(np.ptp(points[:, 0]))
    valid = not contradictory and abs(slope) <= 0.002 and residual <= 0.003 and span >= 0.7
    if contradictory:
        confidence = 0.0
    # Subsample peak fitting can give identical recordings a tiny negative
    # coverage edge. Quantize only a clock whose total displacement is below
    # 1/100 sample across the entire reference (<=0.00021 ms at 48 kHz).
    if (
        max(abs(intercept * sample_rate), abs(intercept * sample_rate + slope * len(reference)))
        < 0.01
    ):
        intercept, slope = 0.0, 0.0
    return Alignment(
        float(intercept),
        float(slope * 1e6),
        confidence,
        len(points),
        residual * 1000,
        "aligned" if valid else "uncertain",
        polarity,
    )
