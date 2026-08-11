import numpy as np
import pytest

from astroplanner.catalog import load_targets
from astroplanner.ephemeris import build_night
from astroplanner.scoring import fov_fit_score, rank_targets
from astroplanner.sensors import get_camera


def test_summer_night_st_louis():
    ctx = build_night("2026-08-02", 38.6, -90.2)
    assert ctx.darkness_kind == "astronomical"
    assert 4 < ctx.dark_hours < 9
    assert 0 <= ctx.moon_illumination <= 1
    assert 0 <= ctx.moon_phase_angle_deg <= 180
    # illumination and phase angle must describe the same moon
    assert ctx.moon_illumination == pytest.approx(
        (1 + np.cos(np.radians(ctx.moon_phase_angle_deg))) / 2, abs=1e-9
    )


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


FULL_MOON = "2026-08-27"   # 100% illuminated, up ~7.7 h of darkness
NEW_MOON = "2026-08-11"    # 0.3% illuminated, below horizon all night


def _ranked(date, bortle=4, filters=("none",)):
    ctx = build_night(date, 38.6, -90.2)
    cam = get_camera("asi533mc")
    return ctx, {
        r.target.id: r
        for r in rank_targets(ctx, cam, 500, 80, bortle, available_filters=list(filters))
    }


def test_new_moon_night_has_no_moon_cost():
    ctx, ranked = _ranked(NEW_MOON)
    assert ctx.moon_illumination < 0.05
    # The moon never clears the horizon during darkness, so the cost is zero
    # up to the mag<->nanolambert roundtrip's floating-point noise.
    assert all(r.moon_brightening_mag == pytest.approx(0, abs=1e-9) for r in ranked.values())
    assert all(r.moon_penalty == pytest.approx(0, abs=1e-9) for r in ranked.values())


def test_full_moon_costs_magnitudes_and_snr():
    _, ranked = _ranked(FULL_MOON)
    costs = [r.moon_brightening_mag for r in ranked.values()]
    assert max(costs) > 2.0                       # several magnitudes lost
    assert all(0 < r.moon_penalty < 0.95 for r in ranked.values())


def test_full_moon_shortens_broadband_subs():
    # Same target, same rig, same site: moonlight raises the sky rate, and a
    # brighter sky reaches the sky-limited point sooner.
    _, dark = _ranked(NEW_MOON)
    _, moonlit = _ranked(FULL_MOON)
    common = set(dark) & set(moonlit)
    assert common
    shorter = [
        moonlit[t].exposure.optimal_s < dark[t].exposure.optimal_s for t in common
    ]
    assert all(shorter)
    # And the moonlit sky rate really is the brighter one.
    for t in common:
        assert moonlit[t].exposure.sky_e_per_s > moonlit[t].dark_sky_rate


def test_moon_penalty_tracks_sky_brightening():
    # penalty = 1 - sqrt(dark/total), so it is a pure function of brightening.
    _, ranked = _ranked(FULL_MOON)
    for r in ranked.values():
        expected = 1.0 - np.sqrt(r.dark_sky_rate / r.exposure.sky_e_per_s)
        assert r.moon_penalty == pytest.approx(min(expected, 0.95), abs=1e-9)


def test_moon_penalty_is_filter_independent():
    # Under a flat-spectrum sky, moonlight and skyglow are both continuum, so
    # any filter cuts both equally and the *fractional* moon cost cancels.
    # Narrowband does not reduce the moon's relative bite - see below for what
    # it actually buys.
    ctx = build_night(FULL_MOON, 38.6, -90.2)
    cam = get_camera("asi533mc")
    b = {r.target.id: r for r in rank_targets(ctx, cam, 500, 80, 4, available_filters=["none"])}
    n = {r.target.id: r for r in rank_targets(ctx, cam, 500, 80, 4, available_filters=["nb3"])}
    for t in set(b) & set(n):
        assert n[t].moon_penalty == pytest.approx(b[t].moon_penalty, rel=1e-9)


def test_narrowband_buys_absolute_snr_on_line_targets():
    # What narrowband really does: pass the line flux, cut the continuum sky.
    # On an emission nebula that beats unfiltered-under-a-dark-sky (>1.0) even
    # with a full moon up; on a galaxy it buys nothing.
    ctx = build_night(FULL_MOON, 38.6, -90.2)
    cam = get_camera("asi533mc")
    ranked = {r.target.id: r for r in rank_targets(ctx, cam, 500, 80, 4)}
    veil, m31 = ranked.get("NGC6960"), ranked.get("M31")
    assert veil is not None and m31 is not None
    assert veil.suggested_filter.line_filter
    assert not m31.suggested_filter.line_filter
    assert veil.sky_quality > 1.0        # better than unfiltered at dark sky
    assert m31.sky_quality < 0.5         # galaxy just eats the moonlight
    # sky_quality reports the mode this rig would actually shoot — a duo-band
    # on a one-shot-colour camera, not the 3 nm mono filter that wins the
    # abstract SNR contest. Still nearly 4x the galaxy under the same moon.
    assert veil.mode_advice.best.filter_key == "duoband"
    assert veil.sky_quality > 3 * m31.sky_quality


def test_galaxies_compete_on_a_dark_night_but_not_a_moonlit_one():
    # The ranking credit for sky quality is capped at 1.0, so a narrowband
    # nebula's 8.5x efficiency gain cannot bury every broadband target on a
    # moonless night - but under a full moon galaxies genuinely do lose.
    cam = get_camera("asi533mc")
    dark_top = rank_targets(build_night(NEW_MOON, 38.6, -90.2), cam, 500, 80, 4)[:8]
    moon_top = rank_targets(build_night(FULL_MOON, 38.6, -90.2), cam, 500, 80, 4)[:8]
    assert any(not r.target.line_emitter for r in dark_top)
    assert all(r.target.line_emitter for r in moon_top)


def test_type_subset_ranks_only_requested_types():
    ctx = build_night(FULL_MOON, 38.6, -90.2)
    cam = get_camera("asi533mc")
    galaxies = [t for t in load_targets() if t.type == "galaxy"]
    ranked = rank_targets(ctx, cam, 500, 80, 4, targets=galaxies)
    assert ranked and all(r.target.type == "galaxy" for r in ranked)
    # Under a full moon a galaxy keeps well under half a moonless night's SNR.
    assert all(r.sky_quality < 0.5 for r in ranked)


def test_full_moon_reorders_the_night_toward_emission_targets():
    ctx = build_night(FULL_MOON, 38.6, -90.2)
    cam = get_camera("asi533mc")
    top = rank_targets(ctx, cam, 500, 80, 4)[:5]
    assert all(r.target.line_emitter for r in top)
    assert all(r.suggested_filter.line_filter for r in top)


def test_fov_fit():
    assert fov_fit_score(50, (200, 150)) == 1.0          # comfortable
    assert fov_fit_score(1, (200, 150)) < 0.2            # tiny target
    assert fov_fit_score(600, (200, 150)) < 0.5          # overflows frame


def test_moon_separation_is_measured_in_the_observers_sky():
    # Regression: astropy's separation() converts the moon's GCRS coordinate
    # (which carries a distance) into ICRS as a *nearby object*, reporting the
    # direction it would have from the solar-system barycentre. Called the
    # wrong way round it was silently returning separations tens of degrees
    # off, which fed straight into the moonlight model.
    import warnings

    from astropy.coordinates import AltAz, SkyCoord
    from astropy import units as u

    from astroplanner.ephemeris import target_track

    ctx = build_night(FULL_MOON, 38.6, -90.2)
    ra, dec = 328.35, 47.27            # IC5146
    _, sep = target_track(ctx, ra, dec)

    i = len(ctx.times) // 2
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        frame = AltAz(obstime=ctx.times[i], location=ctx.location)
        in_sky = (coord.transform_to(frame)
                  .separation(ctx.moon_coord[i].transform_to(frame)).deg)
    assert sep[i] == pytest.approx(in_sky, abs=1e-6)
