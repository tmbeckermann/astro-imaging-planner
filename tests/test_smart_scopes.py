"""Integrated instruments: the sensor and the filters are not yours to choose."""

import pytest

from astroplanner.filters import FILTERS
from astroplanner.scoring import recommend_mode, snr_quality
from astroplanner.sensors import get_camera
from astroplanner.sky import sky_electron_rate, sqm_from_bortle
from astroplanner.telescopes import TELESCOPES, get_telescope

SMART = ["seestar50", "dwarf2", "dwarf3", "dwarf3-wide",
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
        assert scope.fixed_camera in {"imx462", "imx415", "imx678", "imx678-wide",
                                      "imx347", "imx662", "os02k10"}
        assert scope.builtin_filters, key
        assert scope.kind == "smart"


def test_published_fields_of_view_reproduce():
    # The check that the aperture/focal-length/pixel-pitch triples are right:
    # each maker publishes a field of view, and the numbers here have to
    # produce it. Tolerance is a few percent — makers round, and some quote the
    # illuminated circle rather than the sensor.
    expected_deg = {                 # (width, height) as published
        "seestar50": (1.29, 0.73),
        "dwarf2": (3.19, 1.79),      # 3840 x 2160 delivered, at 1.45 um
        "dwarf3-wide": (47.9, 27.0),  # 1920 x 1080 at the 2.92 um its 45 mm-equiv implies

        "dwarf3": (2.93, 1.65),      # 3840 x 2160 delivered, at 2.0 um
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
    for key in ("seestar50", "dwarf3", "dwarf-mini"):
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


def test_exposure_ceilings_come_from_the_makers():
    # Published: 90 s on the mini, 60 s on the DWARF 3 in EQ mode, 15 s on the
    # DWARF II. Unknown on the Seestar and the eQuinox, and an unknown limit is
    # not the same as no limit, so those stay None.
    assert get_telescope("dwarf-mini").max_sub_s == 90
    assert get_telescope("dwarf3").max_sub_s == 60
    assert get_telescope("dwarf2").max_sub_s == 15
    for key in ("seestar50", "equinox2"):
        assert get_telescope(key).max_sub_s is None, key


def test_a_fifteen_second_ceiling_bites_at_every_site_worth_driving_to():
    # The DWARF II's 15 s cap is the constraint anywhere darker than a bright
    # suburb: its unfiltered optimum is 50 s at Bortle 5 and 180 s at Bortle 1,
    # none of which it will expose. Only under city glow does the sky arrive
    # fast enough for 15 s to be more than the instrument allows.
    for bortle in (1, 4, 6):
        a = advise("dwarf2", line_emitter=False, bortle=bortle)
        assert a.scores["visible"].sub_capped, bortle
        assert a.scores["visible"].recommended_sub_s == 15
    for bortle in (7, 9):
        a = advise("dwarf2", line_emitter=False, bortle=bortle)
        assert not a.scores["visible"].sub_capped, bortle
        assert a.scores["visible"].recommended_sub_s <= 15, bortle
    # Under real city glow the optimum is a couple of seconds, well inside it.
    assert advise("dwarf2", line_emitter=False, bortle=9).scores["visible"].recommended_sub_s == 5


def test_an_astro_filter_position_is_not_assumed_to_reject_light_pollution():
    # The DWARFs list a filter called "Astro". Whether it merely cuts UV/IR or
    # also notches light pollution is not stated, and the two differ by ~1.4x in
    # SNR under a city sky. Modelled as the plain UV/IR cut: understating a
    # filter costs you a target, overstating it costs you the night.
    for key in ("dwarf-mini", "dwarf3"):
        assert "cls" not in get_telescope(key).builtin_filters, key
        assert get_telescope(key).builtin_filters == ("none", "duoband-wide"), key
    # The wide lenses see the astro position but not the dual-band.
    for key in ("dwarf3-wide", "dwarf-mini-wide"):
        assert get_telescope(key).builtin_filters == ("none",), key


def test_the_wide_angle_module_is_a_different_instrument():
    # Different lens, different sensor, no filter in front of it — so it is its
    # own entry rather than a corrector on the telephoto.
    wide = get_telescope("dwarf-mini-wide")
    tele = get_telescope("dwarf-mini")
    assert wide.fixed_camera != tele.fixed_camera
    assert wide.builtin_filters == ("none",)
    assert wide.max_sub_s == tele.max_sub_s == 90


def test_every_optical_figure_is_now_published():
    # The mini's full table gives 3.4 mm on the wide lens, which is what was
    # inferred from the DWARF 3's identical module. Nothing optical is left
    # guessed: what remains unstated is which of its two 2.9 um sensors sits
    # behind which lens, and that moves read noise and QE, not geometry.
    mini_wide = get_telescope("dwarf-mini-wide")
    assert (mini_wide.aperture_mm, mini_wide.focal_length_mm) == (3.4, 6.7)
    assert mini_wide.f_ratio == pytest.approx(2.0, abs=0.05)
    assert not mini_wide.aperture_assumed
    for key in ("dwarf-mini", "dwarf-mini-wide"):
        assert get_telescope(key).assumed == ("sensor pairing",), key

    # The DWARF 3's wide module is fully published now — optics from the
    # comparison table, sensor geometry from its 45 mm equivalent.
    d3_wide = get_telescope("dwarf3-wide")
    assert d3_wide.assumed == ()
    assert (d3_wide.aperture_mm, d3_wide.focal_length_mm) == (3.4, 6.7)

    # Published entries claim nothing.
    for key in ("dwarf2", "dwarf3", "seestar50", "equinox2"):
        assert get_telescope(key).assumed == (), key


def test_the_dwarf3_telephoto_matches_its_published_figures():
    # 35 mm at 150 mm, IMX678, 2.00 um. The app reports the sensor's full array
    # (3856 x 2180); the maker's table reports the picture it writes
    # (3840 x 2160), and the picture is what you frame with.
    scope, cam = get_telescope("dwarf3"), get_camera("imx678")
    assert (scope.aperture_mm, scope.focal_length_mm) == (35.0, 150.0)
    assert scope.f_ratio == pytest.approx(4.29, abs=0.01)
    assert (cam.width_px, cam.height_px, cam.pixel_um) == (3840, 2160, 2.00)
    assert scope.builtin_filters == ("none", "duoband-wide")


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
    # 24 mm refractor at 100 mm f4.2, IMX415, 3840 x 2160 delivered, 15 s
    # ceiling, and — per the comparison table — VIS and IR-pass built in, with
    # no dual-band. That last one changes its advice completely.
    scope, cam = get_telescope("dwarf2"), get_camera("imx415")
    assert (scope.aperture_mm, scope.focal_length_mm) == (24, 100)
    assert scope.f_ratio == pytest.approx(4.2, abs=0.05)
    assert (cam.width_px, cam.height_px, cam.pixel_um) == (3840, 2160, 1.45)
    assert scope.max_sub_s == 15
    assert scope.builtin_filters == ("none",)

    a = advise("dwarf2", line_emitter=True)
    assert a.recommended == "visible"                 # nothing else is fitted
    assert "no line filter available" in a.reason


def test_the_dwarf2_has_no_wide_angle_rig_because_it_cannot_shoot_one():
    # Its table reads "Wide-Angle Picture: N/A" and "Astro (Tele)": the lens
    # exists, the exposure mode does not. Offering it as a planning target
    # would be offering a session the instrument refuses to take.
    assert "dwarf2-wide" not in TELESCOPES


def test_the_published_equivalent_focal_lengths_reproduce():
    # A 35 mm-equivalent focal length is a statement about sensor diagonal, so
    # it independently checks the pixel pitch and pixel count together.
    for key, cam_key, equiv in [("dwarf3", "imx678", 737), ("dwarf2", "imx415", 675),
                                ("dwarf3-wide", "imx678-wide", 45)]:
        scope, cam = get_telescope(key), get_camera(cam_key)
        diag_mm = ((cam.width_mm) ** 2 + (cam.height_mm) ** 2) ** 0.5
        got = scope.focal_length_mm * 43.267 / diag_mm
        assert got == pytest.approx(equiv, rel=0.03), f"{key}: {got:.0f} mm equivalent"


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

    # ...and the surviving wide entries are both f/2.0.
    for key in ("dwarf3-wide", "dwarf-mini-wide"):
        assert get_telescope(key).f_ratio == pytest.approx(2.0, abs=0.05), key


def test_the_minis_published_diagonals_and_equivalents_reproduce():
    # Its table gives two independent cross-checks per lens: a diagonal field
    # of view and a 35 mm-equivalent focal length. Both follow from 1920 x 1080
    # at 2.9 um, and both would break if the pixel pitch or count were wrong.
    import math

    for key, equiv, diag_deg in [("dwarf-mini", 1016, 2.45), ("dwarf-mini-wide", 45, 50.59)]:
        scope, cam = get_telescope(key), get_camera(get_telescope(key).fixed_camera)
        diag_mm = math.hypot(cam.width_mm, cam.height_mm)
        got_equiv = scope.focal_length_mm * 43.267 / diag_mm
        got_diag = 2 * math.degrees(math.atan(diag_mm / 2 / scope.focal_length_mm))
        assert got_equiv == pytest.approx(equiv, rel=0.02), f"{key}: {got_equiv:.0f} mm equivalent"
        assert got_diag == pytest.approx(diag_deg, rel=0.02), f"{key}: {got_diag:.2f} deg diagonal"


def test_the_minis_stated_sensor_size_contradicts_its_own_table():
    # Guarding a documented spec-sheet error: the mini's table also prints
    # "Sensor Size 7.712 x 4.352 mm", which is a 3856 x 2176 array at 2.0 um —
    # the DWARF 3's sensor, not this one. Taking it at face value would give a
    # 3.4-degree telephoto field against the 2.45 degrees the same table
    # publishes, so the resolution and pixel size win.
    import math

    cam = get_camera(get_telescope("dwarf-mini").fixed_camera)
    assert (cam.width_mm, cam.height_mm) == pytest.approx((5.568, 3.132), rel=1e-3)
    bogus = 2 * math.degrees(math.atan(math.hypot(7.712, 4.352) / 2 / 150))
    assert bogus > 3.3                      # what the stated size would imply
