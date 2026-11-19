import math
from datetime import datetime

from deviceon_mcp.analysis import _pattern_onset, analyze_periodicity, pearson

NOW = 1_800_000_000_000
STEP = 5_000


def square_wave(period_ms, high_ms, window_ms, hi=90.0, lo=8.0):
    pts = []
    t = NOW - window_ms
    while t <= NOW:
        pts.append((t, hi if (t % period_ms) < high_ms else lo))
        t += STEP
    return pts


def test_detects_periodic_spikes():
    r = analyze_periodicity(square_wave(180_000, 60_000, 30 * 60_000), NOW, 30 * 60_000)
    assert r["periodic"] is True
    assert abs(r["period_sec"] - 180) <= 5
    assert abs(r["duty_cycle"] - 0.33) <= 0.05
    assert r["baseline"] == 8.0 and r["peak_avg"] == 90.0
    assert r["confidence"] == "high"
    assert 0 <= r["next_peak_eta_sec"] <= 180


def test_flat_series_is_not_anomalous():
    pts = [(NOW - i * STEP, 10.0 + (i % 3)) for i in range(200)]
    r = analyze_periodicity(pts, NOW, 200 * STEP)
    assert r["anomalous"] is False and r["periodic"] is False
    assert any("no significant spikes" in n for n in r["notes"])


def test_irregular_spikes_are_not_periodic():
    starts = [60_000, 200_000, 260_000, 700_000, 760_000, 1_500_000]
    window = 1_800_000
    pts = []
    for i in range(window // STEP + 1):
        t = NOW - window + i * STEP
        rel = t - (NOW - window)
        pts.append((t, 90.0 if any(s <= rel < s + 30_000 for s in starts) else 8.0))
    r = analyze_periodicity(pts, NOW, window)
    assert r["anomalous"] is True
    assert r["periodic"] is False


def test_too_few_samples():
    r = analyze_periodicity([(NOW, 1.0), (NOW - STEP, 2.0)], NOW, 60_000)
    assert r["periodic"] is False and r["samples"] == 2


def test_coarse_sampling_is_flagged():
    # 60 s samples for 30 s spikes: should warn rather than claim precision
    pts = [(NOW - i * 60_000, 90.0 if i % 6 == 0 else 8.0) for i in range(60)]
    r = analyze_periodicity(pts, NOW, 60 * 60_000)
    assert any("too coarse" in n for n in r["notes"])


def test_pearson():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert pearson([1, 1, 1], [1, 2, 3]) is None


# ---- recent-onset fallback ---------------------------------------------------
# Shaped like the real DESKTOP-MT3CC6E data: 60 s samples, idle memory ~19% drifting
# ~9 points, then a scheduled job adding +26 points (grow 120 s, hold 150 s, every 360 s).

MIN = 60_000


def memory_series(window_min, onset_min_ago=None, one_off_min_ago=None):
    pts = []
    for i in range(window_min + 1):
        t = NOW - (window_min - i) * MIN
        v = 19 + 3.5 * math.sin(i * 0.37) + ((i * 7) % 5) * 0.4
        if onset_min_ago is not None and t >= NOW - onset_min_ago * MIN:
            phase = (t - (NOW - onset_min_ago * MIN)) % (6 * MIN)
            v += 26 * min(1.0, phase / (2 * MIN)) if phase < 270_000 else 0
        if one_off_min_ago is not None and NOW - one_off_min_ago * MIN <= t < NOW - (one_off_min_ago - 3) * MIN:
            v += 26
        pts.append((t, v))
    return pts


def test_recent_onset_is_found_in_tail_window():
    # 15 min of pattern in a 180 min window (~5% of samples): the full window misses it
    r = analyze_periodicity(memory_series(180, onset_min_ago=15), NOW, 180 * MIN)
    assert r["periodic"] is True
    assert abs(r["period_sec"] - 360) <= 60
    assert r["analyzed_window_min"] == 90
    assert r["full_window"]["anomalous"] is False  # diluted over the full window
    # first sample above threshold is ~1-2 min after the job starts (it ramps up)
    started = datetime.fromisoformat(r["pattern_started_at"]).timestamp() * 1000
    assert NOW - 15 * MIN <= started <= NOW - 12 * MIN
    assert "only present in the most recent 90 min" in r["notes"][0]


def test_onset_ignores_an_unrelated_earlier_spike():
    # pattern starts 15 min ago; a one-off spike 25 min ago is 10 min before it (not ~6 min),
    # so it must not be taken as the start of the pattern.
    pts = memory_series(180, onset_min_ago=15, one_off_min_ago=25)
    step = MIN
    onset = _pattern_onset(pts, threshold=31.0, step=step, period_ms=360_000,
                           max_jitter_ratio=0.2)
    assert NOW - 15 * MIN <= onset <= NOW - 12 * MIN
    # an earlier spike that DOES fit the period extends the pattern backwards
    pts2 = memory_series(180, onset_min_ago=21)
    onset2 = _pattern_onset(pts2, threshold=31.0, step=step, period_ms=360_000,
                            max_jitter_ratio=0.2)
    assert NOW - 21 * MIN <= onset2 <= NOW - 18 * MIN


def test_full_window_result_unchanged_when_already_periodic():
    r = analyze_periodicity(square_wave(180_000, 60_000, 30 * 60_000), NOW, 30 * 60_000)
    assert r["periodic"] is True
    assert "analyzed_window_min" not in r and "pattern_started_at" not in r


def test_noise_only_is_not_made_periodic_by_tail_windows():
    r = analyze_periodicity(memory_series(180), NOW, 180 * MIN)
    assert r["periodic"] is False and "analyzed_window_min" not in r


def test_tail_windows_never_shorter_than_10_minutes():
    # 15 min window: halves would be 7.5 min -> no fallback attempted
    r = analyze_periodicity(memory_series(15, onset_min_ago=5), NOW, 15 * MIN)
    assert "analyzed_window_min" not in r
