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


def analyze_periodicity(
    points: list[tuple[int, float]],
    now_ms: int,
    window_ms: int,
    min_amplitude: float = 20.0,
    max_jitter_ratio: float = 0.2,
) -> dict:
    """Detect recurring spikes in a (ts_ms, value) series.

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

    # Group consecutive high samples; a data gap (> 3 steps) breaks a segment.
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

    # Merge spikes split by a single dipped sample.
    merged: list[_Segment] = []
    for seg in segments:
        if merged and seg.start - merged[-1].end <= 2 * step:
            merged[-1].end = seg.end
            merged[-1].values.extend(seg.values)
        else:
            merged.append(seg)
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
