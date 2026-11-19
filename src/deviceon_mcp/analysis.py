"""Pure-Python signal analysis: spike/periodicity detection and correlation.

Kept dependency-free on purpose; the series are small (<= 10k points).
The LLM gets the structured result, never the raw series.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone


def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n != len(ys) or n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass
class _Segment:
    start: int
    end: int
    values: list[float]
    truncated_start: bool = False
    truncated_end: bool = False


def _segments(pts: list[tuple[int, float]], threshold: float, step: float) -> list[_Segment]:
    """Group consecutive samples >= threshold into spikes.

    A data gap (> 3 steps) breaks a spike; spikes split by a single dipped sample are merged.
    """
    segments: list[_Segment] = []
    cur: _Segment | None = None
    prev_ts = None
    for t, v in pts:
        gap = prev_ts is not None and t - prev_ts > 3 * step
        if v >= threshold:
            if cur is None or gap:
                if cur is not None:
                    segments.append(cur)
                cur = _Segment(t, t, [v])
            else:
                cur.end = t
                cur.values.append(v)
        elif cur is not None:
            segments.append(cur)
            cur = None
        prev_ts = t
    if cur is not None:
        segments.append(cur)

    merged: list[_Segment] = []
    for seg in segments:
        if merged and seg.start - merged[-1].end <= 2 * step:
            merged[-1].end = seg.end
            merged[-1].values.extend(seg.values)
        else:
            merged.append(seg)
    return merged


# Recent-onset fallback: when the full window shows nothing, retry on its most recent
# 1/2, 1/4, 1/8 (longest first: more periods = more evidence), but never on less than
# 10 minutes or 10 samples.
_TAIL_DIVISORS = (2, 4, 8)
_MIN_TAIL_MS = 10 * 60_000
_MIN_TAIL_SAMPLES = 10


def analyze_periodicity(
    points: list[tuple[int, float]],
    now_ms: int,
    window_ms: int,
    min_amplitude: float = 20.0,
    max_jitter_ratio: float = 0.2,
) -> dict:
    """Detect recurring spikes in a (ts_ms, value) series.

    First analyses the whole window. If no periodic pattern is found there, a pattern that
    started recently may have been diluted by the quiet part of the window (the high level
    is taken at p95, which assumes spikes fill >= 5% of the samples). So the most recent
    1/2, 1/4, 1/8 of the window are tried in turn with the SAME acceptance criteria; the
    first periodic one is returned, together with when the pattern started
    (pattern_started_at) and analyzed_window_min. No extra data is fetched.
    """
    full = _analyze_core(points, now_ms, window_ms, min_amplitude, max_jitter_ratio)
    if full["periodic"] or full["samples"] < 10:
        return full

    pts = sorted({ts: v for ts, v in points}.items())
    step = statistics.median(b[0] - a[0] for a, b in zip(pts, pts[1:]) if b[0] > a[0])
    for div in _TAIL_DIVISORS:
        tail_ms = window_ms // div
        if tail_ms < _MIN_TAIL_MS:
            break
        tail_start = now_ms - tail_ms
        tail = [p for p in pts if p[0] >= tail_start]
        if len(tail) < _MIN_TAIL_SAMPLES:
            break
        r = _analyze_core(tail, now_ms, tail_ms, min_amplitude, max_jitter_ratio)
        if not r["periodic"]:
            continue
        tail_min = round(tail_ms / 60_000)
        r["analyzed_window_min"] = tail_min
        r["full_window"] = {"samples": full["samples"], "anomalous": full["anomalous"], "notes": full["notes"]}
        onset = _pattern_onset(pts, r["threshold"], step, r["period_sec"] * 1000, max_jitter_ratio)
        since = ""
        if onset is not None:
            r["pattern_started_at"] = _iso(onset)
            since = f" (started ~{r['pattern_started_at']})"
        r["notes"].insert(
            0,
            f"the pattern is only present in the most recent {tail_min} min{since}; over the full "
            f"{round(window_ms / 60_000)} min window it was diluted below the detection threshold.",
        )
        return r
    return full


def _pattern_onset(
    pts: list[tuple[int, float]],
    threshold: float,
    step: float,
    period_ms: float,
    max_jitter_ratio: float,
) -> int | None:
    """When the periodic pattern began.

    The pattern is ongoing, so the newest spike belongs to it. Walk back over earlier spikes
    (whole series, same threshold) while each is one period before the next; the first one
    that breaks the rhythm (a one-off spike, or quiet time) ends the walk. A single missed
    spike also ends it, so the result can be later than the true start, never earlier.
    """
    starts = [s.start for s in _segments(pts, threshold, step)]
    if not starts:
        return None
    i = len(starts) - 1
    tol = max(max_jitter_ratio * period_ms, 2 * step)
    while i > 0 and abs((starts[i] - starts[i - 1]) - period_ms) <= tol:
        i -= 1
    return starts[i]


def _analyze_core(
    points: list[tuple[int, float]],
    now_ms: int,
    window_ms: int,
    min_amplitude: float = 20.0,
    max_jitter_ratio: float = 0.2,
) -> dict:
    """Detect recurring spikes in one window.

    Approach: split samples into high/low around the midpoint between the 20th and
    95th percentile, group consecutive highs into spike segments, then check whether
    spike start times recur at a stable interval (median absolute deviation of the
    intervals <= max_jitter_ratio * period). Autocorrelation at that lag is reported
    as supporting evidence.
    """
    pts = sorted({ts: v for ts, v in points}.items())
    n = len(pts)
    result: dict = {"samples": n, "periodic": False, "anomalous": False, "notes": []}
    if n < 10:
        result["notes"].append(f"only {n} samples in window; need >= 10. Check report interval / history storage.")
        return result

    ts = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    diffs = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    step = statistics.median(diffs)
    result["sample_interval_sec"] = round(step / 1000, 1)
    result["data_staleness_sec"] = round((now_ms - ts[-1]) / 1000, 1)
    coverage = min(1.0, (n * step) / window_ms) if window_ms > 0 else 1.0
    result["coverage_ratio"] = round(coverage, 2)
    if coverage < 0.8:
        result["notes"].append("history has gaps (coverage < 80%); results may be unreliable.")
    if now_ms - ts[-1] > 5 * step:
        result["notes"].append("latest sample is old; device may have stopped reporting.")

    sv = sorted(vals)
    low, high = quantile(sv, 0.20), quantile(sv, 0.95)
    threshold = low + (high - low) / 2
    result.update(
        baseline=round(statistics.median(v for v in vals if v < threshold) if any(v < threshold for v in vals) else low, 1),
        threshold=round(threshold, 1),
        max=round(sv[-1], 1),
    )
    if high - low < min_amplitude:
        result["notes"].append(
            f"no significant spikes: p95-p20 spread {high - low:.1f} < min_amplitude {min_amplitude}."
        )
        return result

    merged = _segments(pts, threshold, step)
    if merged:
        merged[0].truncated_start = merged[0].start == ts[0]
        merged[-1].truncated_end = merged[-1].end == ts[-1]

    peak_vals = [v for s in merged for v in s.values]
    result["anomalous"] = True
    result["peak_count"] = len(merged)
    result["peak_avg"] = round(sum(peak_vals) / len(peak_vals), 1)
    complete = [s for s in merged if not s.truncated_start and not s.truncated_end]
    if complete:
        result["peak_duration_sec"] = round(statistics.median(s.end - s.start + step for s in complete) / 1000, 1)
        if statistics.median(s.end - s.start + step for s in complete) < 3 * step:
            result["notes"].append(
                "spikes last < 3 samples; sampling interval is too coarse to measure them reliably. "
                "Lower the device report interval."
            )
    last = merged[-1]
    result["last_peak_start"] = _iso(last.start)
    result["in_peak_now"] = last.truncated_end and result["data_staleness_sec"] <= 2 * step / 1000

    starts = [s.start for s in merged if not s.truncated_start]
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    if len(intervals) < 2:
        result["notes"].append(
            f"only {len(starts)} complete spike(s) observed; need >= 3 to judge periodicity. Widen window_min."
        )
        return result

    period = statistics.median(intervals)
    jitter = statistics.median(abs(i - period) for i in intervals) / period
    result["period_sec"] = round(period / 1000, 1)
    result["period_jitter_ratio"] = round(jitter, 3)
    if jitter > max_jitter_ratio:
        result["notes"].append("spikes recur irregularly (high jitter); treat as intermittent, not periodic.")
        return result

    result["periodic"] = True
    if "peak_duration_sec" in result:
        result["duty_cycle"] = round(result["peak_duration_sec"] * 1000 / period, 2)

    # Supporting evidence: autocorrelation of an evenly resampled series at lag = period.
    lag = round(period / step)
    grid: list[float] = []
    j = 0
    t = ts[0]
    while t <= ts[-1]:
        while j + 1 < n and ts[j + 1] <= t:
            j += 1
        grid.append(vals[j])
        t += step
    acf = pearson(grid[:-lag], grid[lag:]) if 0 < lag < len(grid) // 2 else None
    result["autocorr_at_period"] = round(acf, 2) if acf is not None else None
    if acf is not None and acf >= 0.5 and len(starts) >= 4:
        result["confidence"] = "high"
    elif acf is None or acf >= 0.2:
        result["confidence"] = "medium"
    else:
        result["confidence"] = "low"

    if result["in_peak_now"]:
        result["next_peak_eta_sec"] = 0
    else:
        nxt = last.start + period
        while nxt < now_ms:
            nxt += period
        result["next_peak_eta_sec"] = round((nxt - now_ms) / 1000)
    return result
