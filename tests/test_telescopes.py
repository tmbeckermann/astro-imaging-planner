"""Telescope database and what a reducer does to the numbers."""

import pytest

from astroplanner.exposure import optimal_sub_exposure
from astroplanner.filters import FILTERS
from astroplanner.sensors import get_camera
from astroplanner.sky import sky_electron_rate, sqm_from_bortle
from astroplanner.telescopes import TELESCOPES, get_telescope


def test_every_scope_has_a_sane_f_ratio():
    for key, t in TELESCOPES.items():
        assert 1.5 < t.f_ratio < 12, key
        assert t.aperture_mm > 0 and t.focal_length_mm > 0


def test_native_train_is_the_catalog_spec():
    gt71 = get_telescope("gt71")
    assert gt71.train() == (420, 71)
    assert gt71.train("native") == (420, 71)


def test_reducer_shortens_focal_length_and_leaves_aperture_alone():
    fl, aperture = get_telescope("edgehd8").train("0.7x reducer")
    assert fl == pytest.approx(2032 * 0.7)
    assert aperture == 203


def test_unknown_corrector_says_what_the_options_are():
    with pytest.raises(KeyError, match="0.7x reducer"):
        get_telescope("edgehd8").train("2x barlow")


def test_unknown_scope_lists_known_keys():
    with pytest.raises(KeyError, match="rasa8"):
        get_telescope("not-a-scope")


def test_a_reducer_halves_the_sub_length():
    # A 0.7x reducer spreads the same photons over (1/0.7)^2 = 2.04x fewer
    # pixels, so each pixel fills twice as fast and goes sky-limited twice as
    # soon. This is the whole reason the sub length is a property of the rig
    # and not of the camera.
    cam = get_camera("asi2600mc")
    sqm = sqm_from_bortle(5)
    scope = get_telescope("edgehd8")

    def rate(corrector):
        fl, aperture = scope.train(corrector)
        return sky_electron_rate(sqm, aperture, cam.pixel_scale(fl), cam.qe, FILTERS["none"])

    native, reduced = rate("native"), rate("0.7x reducer")
    assert reduced / native == pytest.approx(1 / 0.7**2, rel=1e-6)
    t_native = optimal_sub_exposure(cam.read_noise_e, native).optimal_s
    t_reduced = optimal_sub_exposure(cam.read_noise_e, reduced).optimal_s
    assert t_reduced / t_native == pytest.approx(0.7**2, rel=1e-6)


def test_aperture_not_f_ratio_sets_the_sky_rate_at_fixed_pixel_scale():
    # Sampled the same way, the bigger aperture collects more sky per pixel —
    # "fast f/ratio" is a statement about pixel scale, not about photons.
    cam = get_camera("asi533mc")
    sqm = sqm_from_bortle(5)
    small = sky_electron_rate(sqm, 80, 2.0, cam.qe, FILTERS["none"])
    big = sky_electron_rate(sqm, 200, 2.0, cam.qe, FILTERS["none"])
    assert big / small == pytest.approx((200 / 80) ** 2, rel=1e-6)
