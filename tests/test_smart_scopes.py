"""Integrated instruments: the sensor and the filters are not yours to choose."""

import pytest

from astroplanner.filters import FILTERS
from astroplanner.scoring import recommend_mode, snr_quality
from astroplanner.sensors import get_camera
from astroplanner.sky import sky_electron_rate, sqm_from_bortle
from astroplanner.telescopes import TELESCOPES, get_telescope

SMART = ["seestar50", "dwarf2", "dwarf2-wide", "dwarf3", "dwarf3-wide",
         "dwarf-mini", "dwarf-mini-wide", "equinox2"]


def advise(scope_key, line_emitter, bortle=6):
    scope = get_telescope(scope_key)
    cam = get_camera(scope.fixed_camera)
    fl, aperture = scope.train()
    sqm = sqm_from_bortle(bortle)
    scale = cam.pixel_scale(fl)
    rate = lambda f: sky_electron_rate(sqm, aperture, scale, cam.qe, f)
    reference = snr_quality(FILTERS["none"], False, rate(FILTERS["none"]), cam)
    return recommend_mode(line_emitter, cam, rate, reference, set(scope.builtin_filters),
                          max_sub_s=scope.max_sub_s or 1200.0)


def test_the_smart_scopes_are_all_there():
    for key in SMART:
        scope = get_telescope(key)
        assert scope.integrated
        assert scope.fixed_camera in {"imx462", "imx415", "imx678", "imx347", "imx662", "os02k10"}
        assert scope.builtin_filters, key
        assert scope.kind == "smart"


def test_published_fields_of_view_reproduce():
    # The check that the aperture/focal-length/pixel-pitch triples are right:
    # each maker publishes a field of view, and the numbers here have to
    # produce it. Tolerance is a few percent — makers round, and some quote the
    # illuminated circle rather than the sensor.
    expected_deg = {                 # (width, height) as published
        "seestar50": (1.29, 0.73),
        "dwarf2": (3.21, 1.82),    # 3864 x 2192 at 1.45 um; the table rounds to 180'

        "dwarf3": (2.9, 1.6),      # 3856 x 2180 at 2.0 um, per the app
        "equinox2": (0.75, 0.57),    # 45' x 34'
        "dwarf-mini": (2.13, 1.20),  # 30 mm f/5, IMX662 at 1920x1080
    }
    for key, (want_w, want_h) in expected_deg.items():
        scope = get_telescope(key)
        cam = get_camera(scope.fixed_camera)
        fl, _ = scope.train()
        got_w, got_h = (v / 60 for v in cam.fov_arcmin(fl))
        assert got_w == pytest.approx(want_w, rel=0.07), f"{key} width {got_w:.2f} deg"
        assert got_h == pytest.approx(want_h, rel=0.07), f"{key} height {got_h:.2f} deg"


def test_an_instrument_without_a_filter_slot_cannot_be_told_to_use_one():
    # The eQuinox 2 has no filter drawer, so "put a duo-band on it" is not
    # advice — it is a purchase order for a different telescope.
    a = advise("equinox2", line_emitter=True)
    assert not a.scores["line"].available
    assert a.scores["line"].note == "not fitted to this rig"
    assert a.recommended == "visible"
    assert "no line filter available" in a.reason


def test_a_built_in_dual_band_is_used_when_there_is_one():
    for key in ("seestar50", "dwarf2", "dwarf3", "dwarf-mini"):
        a = advise(key, line_emitter=True)
        assert a.recommended == "line", key
        assert a.scores["line"].filter_key == "duoband-wide"


def test_the_wide_dual_band_wins_less_than_a_7nm_would():
    # Smart telescopes ship a wide dual-band, not a 7 nm: about 2x a visible
    # train on an emission target rather than about 4x. Worth knowing before
    # comparing a Seestar's numbers against a filter-wheel rig's.
    wide = advise("dwarf3", line_emitter=True)
    assert 1.8 < wide.scores["line"].sky_quality < 3.0
    assert FILTERS["duoband-wide"].sky_bandwidth_factor > FILTERS["duoband"].sky_bandwidth_factor


def test_broadband_targets_still_get_the_visible_train():
    for key in SMART:
        a = advise(key, line_emitter=False)
        assert a.recommended == "visible", key


def test_full_spectrum_is_never_offered_on_a_sealed_instrument():
    # None of them fit one, so the mode is unavailable whatever the sensor
    # would allow in principle.
    for key in SMART:
        a = advise(key, line_emitter=False)
        assert not a.scores["full"].available, key


def test_a_smart_scope_resolution_is_coarse_and_that_shows():
    # A 100 mm lens on 1.45 um pixels samples at ~3 arcsec/px. That is the
    # trade these instruments make for their field, and the planner should
    # report it rather than flatter it.
    dwarf2 = get_telescope("dwarf2")
    scale = get_camera(dwarf2.fixed_camera).pixel_scale(dwarf2.focal_length_mm)
    assert scale == pytest.approx(2.99, abs=0.05)
    equinox = get_telescope("equinox2")
    assert get_camera(equinox.fixed_camera).pixel_scale(equinox.focal_length_mm) < 1.2


def test_ordinary_telescopes_are_not_integrated():
    for key, scope in TELESCOPES.items():
        if key in SMART:
            continue
        assert not scope.integrated, key
        assert scope.builtin_filters is None


def test_an_exposure_ceiling_is_reported_rather_than_ignored():
    # The DWARF mini stops at 90 s. Under a dark sky its dual-band optimum runs
    # past that, and the honest advice is "you cannot get there" — not a number
    # you cannot dial into the app.
    mini = get_telescope("dwarf-mini")
    assert mini.max_sub_s == 90
    dark = advise("dwarf-mini", line_emitter=True, bortle=2)
    line = dark.scores["line"]
    assert line.sub_capped
    assert line.recommended_sub_s == 90

    # In a city the sky is bright enough that the optimum fits inside the
    # ceiling, and nothing is flagged.
    city = advise("dwarf-mini", line_emitter=True, bortle=8)
    assert not city.scores["line"].sub_capped
    assert city.scores["line"].recommended_sub_s < 90


def test_instruments_without_a_known_ceiling_do_not_invent_one():
    # An unknown limit is not the same as no limit, so it stays None rather
    # than being guessed at.
    for key in ("seestar50", "dwarf2", "dwarf3", "equinox2"):
        assert get_telescope(key).max_sub_s is None, key


def test_the_mini_also_carries_a_light_pollution_filter():
    # Its filter set is richer than the other DWARFs': LP as well as the
    # dual-band, which matters under a city sky.
    mini = get_telescope("dwarf-mini")
    assert "cls" in mini.builtin_filters
    assert "duoband-wide" in mini.builtin_filters


def test_the_wide_angle_module_is_a_different_instrument():
    # Different lens, different sensor, no filter in front of it — so it is its
    # own entry rather than a corrector on the telephoto.
    wide = get_telescope("dwarf-mini-wide")
    tele = get_telescope("dwarf-mini")
    assert wide.fixed_camera != tele.fixed_camera
    assert wide.builtin_filters == ("none",)
    assert wide.max_sub_s == tele.max_sub_s == 90


def test_the_wide_angle_aperture_is_flagged_as_an_assumption():
    # The mini's spec sheet repeats the telephoto's 30 mm, which at 6.7 mm
    # focal length would be f/0.22 — below the f/0.5 limit for a lens in air.
    # The DWARF 3's published wide module (3.4 mm at the same 6.7 mm) is the
    # basis instead, but it is still an inference for the mini.
    mini_wide = get_telescope("dwarf-mini-wide")
    assert mini_wide.assumed == ("aperture",) and mini_wide.aperture_assumed
    assert mini_wide.f_ratio == pytest.approx(2.0, abs=0.05)
    assert 6.7 / 30 < 0.5                      # the spec-sheet reading is impossible

    # The DWARF 3's optics are published, so only its sensor is inferred.
    d3_wide = get_telescope("dwarf3-wide")
    assert d3_wide.assumed == ("sensor",) and not d3_wide.aperture_assumed
    assert (d3_wide.aperture_mm, d3_wide.focal_length_mm) == (3.4, 6.7)

    # Published entries claim nothing.
    for key in ("dwarf3", "dwarf-mini", "seestar50", "equinox2"):
        assert get_telescope(key).assumed == (), key


def test_the_dwarf3_telephoto_matches_the_figures_from_the_app():
    # Aperture 35 mm at 150 mm, IMX678 at 3856 x 2180 on 2.00 um pixels.
    scope, cam = get_telescope("dwarf3"), get_camera("imx678")
    assert (scope.aperture_mm, scope.focal_length_mm) == (35.0, 150.0)
    assert scope.f_ratio == pytest.approx(4.29, abs=0.01)
    assert (cam.width_px, cam.height_px, cam.pixel_um) == (3856, 2180, 2.00)


def test_a_wide_field_ranks_big_targets_and_buries_small_ones():
    # 48 degrees across at 89 arcsec/pixel is a constellation camera. The
    # field-of-view term should say so: a 10-arcminute galaxy is 0.6% of the
    # frame and has no business being the top pick.
    from astroplanner.catalog import load_targets
    from astroplanner.scoring import fov_fit_score

    wide = get_telescope("dwarf-mini-wide")
    cam = get_camera(wide.fixed_camera)
    fov = cam.fov_arcmin(wide.focal_length_mm)
    assert min(fov) / 60 > 20                  # degrees, not arcminutes
    by_id = {t.id: t for t in load_targets()}
    assert fov_fit_score(by_id["IC1396"].size_arcmin, fov) > \
           fov_fit_score(by_id["M57"].size_arcmin, fov)
    assert fov_fit_score(by_id["M57"].size_arcmin, fov) == pytest.approx(0.15)


def test_the_dwarf2_matches_its_published_table():
    # 24 mm refractor, 100 mm focal length, f4.2, Sony IMX415 at 3864 x 2192.
    scope, cam = get_telescope("dwarf2"), get_camera("imx415")
    assert (scope.aperture_mm, scope.focal_length_mm) == (24, 100)
    assert scope.f_ratio == pytest.approx(4.2, abs=0.05)
    assert (cam.width_px, cam.height_px, cam.pixel_um) == (3864, 2192, 1.45)


def test_an_unknown_focal_length_does_not_move_the_sub_length():
    # The DWARF II's wide lens publishes f/2.4 but not its focal length. That
    # is survivable: sky rate per pixel goes as aperture^2 x scale^2, aperture
    # is FL/N and scale is 206.265*px/FL, so FL cancels. Only the field of view
    # depends on the guess.
    from astroplanner.sky import sky_electron_rate

    cam = get_camera("os02k10")
    sqm = sqm_from_bortle(5)
    rates = []
    for fl in (3.2, 6.7, 12.0):                 # any focal length at f/2.4
        rates.append(sky_electron_rate(sqm, fl / 2.4, cam.pixel_scale(fl), cam.qe,
                                       FILTERS["none"]))
    assert rates[0] == pytest.approx(rates[1], rel=1e-9)
    assert rates[1] == pytest.approx(rates[2], rel=1e-9)

    # ...and the wide entries differ in sub length only through their f-ratios.
    d2, d3 = get_telescope("dwarf2-wide"), get_telescope("dwarf3-wide")
    assert d2.f_ratio == pytest.approx(2.4, abs=0.05)
    assert d3.f_ratio == pytest.approx(2.0, abs=0.05)
