from deviceon_mcp.analysis import analyze_periodicity, pearson

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
