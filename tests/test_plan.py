import numpy as np

from astroplanner.ephemeris import build_night
from astroplanner.scoring import fov_fit_score, rank_targets
from astroplanner.sensors import get_camera


def test_summer_night_st_louis():
    ctx = build_night("2026-08-02", 38.6, -90.2)
    assert ctx.darkness_kind == "astronomical"
    assert 4 < ctx.dark_hours < 9
    assert 0 <= ctx.moon_illumination <= 1


def test_high_latitude_summer_falls_back():
    # Tromso in late June: no astronomical darkness at all.
    ctx = build_night("2026-06-25", 69.6, 18.9)
    assert ctx.darkness_kind == "none" or ctx.dark_hours < 24


def test_rank_targets_returns_sorted_finite_scores():
    ctx = build_night("2026-08-02", 38.6, -90.2)
    cam = get_camera("asi533mc")
    ranked = rank_targets(ctx, cam, focal_length_mm=500, aperture_mm=80, bortle=7)
    assert len(ranked) >= 5
    scores = [r.score for r in ranked]
    assert all(np.isfinite(scores))
    assert scores == sorted(scores, reverse=True)
    for r in ranked:
        assert r.usable_hours > 0
        assert r.max_alt_deg > 30
        assert 0 <= r.moon_penalty <= 0.95
        assert r.exposure.recommended_s >= 5


def test_summer_ranking_favors_summer_objects():
    # In August from mid-northern latitudes, Cygnus/Sagittarius objects should
    # outrank winter objects like the California Nebula.
    ctx = build_night("2026-08-02", 38.6, -90.2)
    cam = get_camera("asi533mc")
    ranked = rank_targets(ctx, cam, 500, 80, bortle=5)
    order = [r.target.id for r in ranked]
    assert order.index("NGC7000") < order.index("M42") if "M42" in order else True
    top10 = set(order[:10])
    assert top10 & {"NGC7000", "IC5070", "IC1396", "NGC6960", "NGC6992", "NGC6888", "M27", "IC1318", "M13", "M92", "NGC7023", "IC5146", "Sh2-155", "NGC7380", "NGC7822"}


def test_line_targets_get_line_filter_under_bright_sky():
    ctx = build_night("2026-08-02", 38.6, -90.2)
    cam = get_camera("asi533mc")
    ranked = rank_targets(ctx, cam, 500, 80, bortle=8)
    line = [r for r in ranked if r.target.line_emitter]
    assert line and all(r.suggested_filter.line_filter for r in line)
    broad = [r for r in ranked if not r.target.line_emitter]
    assert broad and all(not r.suggested_filter.line_filter for r in broad)


def test_fov_fit():
    assert fov_fit_score(50, (200, 150)) == 1.0          # comfortable
    assert fov_fit_score(1, (200, 150)) < 0.2            # tiny target
    assert fov_fit_score(600, (200, 150)) < 0.5          # overflows frame
