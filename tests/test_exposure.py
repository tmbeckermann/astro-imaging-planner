import math

import pytest

from astroplanner.exposure import optimal_sub_exposure, stack_noise_penalty
from astroplanner.filters import FILTERS
from astroplanner.sky import sky_electron_rate, sqm_from_bortle


def test_formula_matches_closed_form():
    # R=1.0 e-, P=0.1 e-/px/s, 5% -> t = 1 / (0.1025 * 0.1) ~ 97.6 s
    res = optimal_sub_exposure(1.0, 0.1, 5.0)
    assert res.optimal_s == pytest.approx(97.56, rel=1e-3)
    assert res.recommended_s == 120
    assert res.swamp_factor == pytest.approx(9.756, rel=1e-3)


def test_darker_sky_needs_longer_subs():
    bright = optimal_sub_exposure(1.0, 1.0).optimal_s
    dark = optimal_sub_exposure(1.0, 0.01).optimal_s
    assert dark > bright * 50


def test_higher_read_noise_needs_longer_subs():
    low = optimal_sub_exposure(1.0, 0.1).optimal_s
    high = optimal_sub_exposure(3.0, 0.1).optimal_s
    assert high == pytest.approx(9 * low, rel=1e-6)


def test_penalty_at_optimal_length_equals_target():
    res = optimal_sub_exposure(1.5, 0.05, noise_increase_pct=5.0)
    assert stack_noise_penalty(1.5, 0.05, res.optimal_s) == pytest.approx(5.0, abs=0.01)


def test_narrowband_gives_much_longer_subs_than_broadband():
    sqm = sqm_from_bortle(5)
    common = dict(aperture_mm=80, pixel_scale_arcsec=1.55, qe=0.8)
    p_broad = sky_electron_rate(sqm, filt=FILTERS["none"], **common)
    p_nb = sky_electron_rate(sqm, filt=FILTERS["nb7"], **common)
    t_broad = optimal_sub_exposure(1.0, p_broad).optimal_s
    t_nb = optimal_sub_exposure(1.0, p_nb).optimal_s
    assert t_nb / t_broad == pytest.approx(3.4 / 0.08, rel=1e-6)


def test_bortle_ordering():
    rates = [
        sky_electron_rate(sqm_from_bortle(b), 80, 1.55, 0.8, FILTERS["none"])
        for b in range(1, 10)
    ]
    assert all(a < b for a, b in zip(rates, rates[1:]))
    # Sanity: Bortle 5, 80mm f/6.25-ish, IMX533 -> order of a few e-/px/s
    assert 0.1 < rates[4] < 20


def test_zero_sky_rate_rejected():
    with pytest.raises(ValueError):
        optimal_sub_exposure(1.0, 0.0)
