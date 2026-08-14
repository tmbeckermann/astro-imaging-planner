"""The full-spectrum / visible / duo-band recommendation."""

import pytest

from astroplanner.filters import FILTERS, mode_available, mode_filter, mode_label
from astroplanner.scoring import FULL_SPECTRUM_MARGIN, recommend_mode, snr_quality
from astroplanner.sensors import get_camera
from astroplanner.sky import sky_electron_rate, sqm_from_bortle

# A 500 mm f/6.25 rig, one representative sky.
APERTURE, SCALE = 80.0, 1.55


def rate_for(bortle=5, qe=0.8):
    sqm = sqm_from_bortle(bortle)
    return lambda f: sky_electron_rate(sqm, APERTURE, SCALE, qe, f)


def advise(camera_key, line_emitter, bortle=5, allowed=None):
    cam = get_camera(camera_key)
    rf = rate_for(bortle, cam.qe)
    reference = snr_quality(FILTERS["none"], False, rf(FILTERS["none"]))
    return recommend_mode(line_emitter, cam, rf, reference, allowed)


def test_line_emitters_get_the_line_filter_and_it_is_not_close():
    a = advise("asi533mc", line_emitter=True)
    assert a.recommended == "line"
    assert a.scores["line"].sky_quality > 3 * a.scores["visible"].sky_quality


def test_broadband_targets_get_the_visible_train():
    a = advise("asi533mc", line_emitter=False)
    assert a.recommended == "visible"
    assert "colour cast" in a.reason or "deepest" in a.reason


def test_full_spectrum_is_a_near_tie_which_is_why_visible_wins():
    # Opening the near-IR gains ~1.6x sky for ~1.3x signal, so the SNR edge is
    # a couple of percent — under the margin that would justify losing colour.
    a = advise("asi533mc", line_emitter=False)
    edge = a.scores["full"].sky_quality / a.scores["visible"].sky_quality
    assert 1.0 < edge < FULL_SPECTRUM_MARGIN
    assert edge == pytest.approx(1.022, abs=0.01)


def test_the_choice_between_broadband_modes_does_not_depend_on_the_site():
    # Both modes see the same continuum sky, so the ratio cancels: a darker
    # site does not make full spectrum a better idea, it just makes both better.
    dark = advise("asi533mc", line_emitter=False, bortle=2)
    city = advise("asi533mc", line_emitter=False, bortle=8)
    ratio = lambda a: a.scores["full"].sky_quality / a.scores["visible"].sky_quality
    assert ratio(dark) == pytest.approx(ratio(city), rel=1e-9)
    assert dark.recommended == city.recommended == "visible"


def test_stock_camera_cannot_shoot_full_spectrum():
    cam = get_camera("dslr")
    assert cam.builtin_ir_cut
    assert not mode_available("full", cam)
    a = advise("dslr", line_emitter=False)
    assert a.recommended == "visible"
    assert not a.scores["full"].available
    assert "IR-cut" in a.scores["full"].note
    assert "built in" in a.caution


def test_modified_camera_unlocks_full_spectrum():
    assert mode_available("full", get_camera("dslr-mod"))
    a = advise("dslr-mod", line_emitter=False)
    assert a.scores["full"].available


def test_stock_camera_on_an_emission_nebula_is_warned_about_ha():
    stock = advise("dslr", line_emitter=True)
    modded = advise("dslr-mod", line_emitter=True)
    assert stock.recommended == "line"           # still the best of a bad lot
    assert "Ha" in stock.caution
    # The filter is not the problem — the camera is. ~0.20 vs ~0.97 of Ha.
    assert modded.scores["line"].sky_quality > 4 * stock.scores["line"].sky_quality


def test_ha_transmission_applies_to_broadband_modes_too():
    # An unmodified camera loses Ha before any filter is fitted, so it is down
    # on emission nebulae even shooting plain visible.
    stock, modded = get_camera("dslr"), get_camera("dslr-mod")
    vis = FILTERS["none"]
    assert vis.signal_factor(True, stock) == pytest.approx(0.20)
    assert vis.signal_factor(True, modded) == pytest.approx(0.97)
    # ...but its galaxies are unaffected: continuum does not care.
    assert vis.signal_factor(False, stock) == vis.signal_factor(False, modded)


def test_osc_takes_a_duoband_and_mono_takes_a_narrowband():
    assert mode_filter("line", get_camera("asi533mc")).key == "duoband"
    assert mode_filter("line", get_camera("asi2600mm")).key == "nb3"
    assert mode_label("line", get_camera("asi533mc"),
                      mode_filter("line", get_camera("asi533mc"))) == "Duo-band"


def test_the_mode_respects_the_filters_you_actually_own():
    owned = {"duoband"}                     # a duo-band and nothing else
    a = advise("asi533mc", line_emitter=False, allowed=owned)
    assert not a.scores["visible"].available
    assert "not fitted to this rig" in a.scores["visible"].note
    # A 7 nm filter bag makes 'line' mean the 7 nm filter, not the duo-band.
    b = advise("asi533mc", line_emitter=True, allowed={"nb7", "none"})
    assert b.recommended == "line"
    assert b.scores["line"].filter_key == "nb7"


def test_every_mode_reports_its_own_sub_length():
    a = advise("asi533mc", line_emitter=True)
    # Narrower band, darker background, longer sub before it is sky-limited.
    assert a.scores["line"].recommended_sub_s > a.scores["visible"].recommended_sub_s
    assert a.scores["visible"].recommended_sub_s > a.scores["full"].recommended_sub_s
