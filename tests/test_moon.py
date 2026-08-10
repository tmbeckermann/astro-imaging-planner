import numpy as np
import pytest

from astroplanner.moon import (
    airmass,
    brightening_mag,
    mag_to_nanolambert,
    moon_illuminance,
    nanolambert_to_mag,
    phase_angle_from_illumination,
    scattering_function,
    sky_brightness_with_moon,
)

DARK = 21.6  # Bortle 3 zenith sky


def test_airmass_at_zenith_and_horizon():
    assert airmass(0) == pytest.approx(1.0)
    assert airmass(60) == pytest.approx(1.87, rel=0.05)
    assert 4 < airmass(90) < 6          # finite at the horizon by construction


def test_phase_angle_conversion():
    assert phase_angle_from_illumination(1.0) == pytest.approx(0.0)     # full
    assert phase_angle_from_illumination(0.0) == pytest.approx(180.0)   # new
    assert phase_angle_from_illumination(0.5) == pytest.approx(90.0)


def test_magnitude_nanolambert_roundtrip():
    for mu in (17.0, 19.5, 21.9):
        assert nanolambert_to_mag(mag_to_nanolambert(mu)) == pytest.approx(mu, abs=1e-9)


def test_full_moon_is_brighter_than_crescent():
    assert moon_illuminance(0) > moon_illuminance(90) > moon_illuminance(150)


def test_scattering_is_minimised_perpendicular_to_the_moon():
    # Rayleigh scattering carries a cos^2(rho) term, so the darkest sky is
    # 90 deg from the moon; backscatter brightens the anti-moon point again.
    seps = np.array([10.0, 30.0, 45.0, 60.0, 90.0])
    vals = scattering_function(seps)
    assert all(a > b for a, b in zip(vals, vals[1:]))          # falls to 90 deg
    assert scattering_function(150.0) > scattering_function(90.0)  # rises after
    # The true minimum sits a little past 90 deg: the aerosol term is still
    # falling there while the Rayleigh term has already bottomed out.
    grid = np.arange(0.0, 181.0, 1.0)
    assert 88.0 <= grid[scattering_function(grid).argmin()] <= 110.0


def test_moon_below_horizon_costs_nothing():
    assert brightening_mag(DARK, 0.0, 60.0, -5.0, 45.0) == pytest.approx(0.0)


def test_new_moon_costs_almost_nothing():
    # Phase angle 180 = new moon, even if it is up and close by.
    assert brightening_mag(DARK, 180.0, 30.0, 40.0, 45.0) < 0.05


def test_full_moon_close_by_is_severe():
    cost = brightening_mag(DARK, 0.0, 30.0, 50.0, 45.0)
    assert cost > 3.0          # several magnitudes of sky brightening
    combined = sky_brightness_with_moon(DARK, 0.0, 30.0, 50.0, 45.0)
    assert combined < DARK     # brighter sky = smaller mag/arcsec^2


def test_separation_matters_under_the_same_moon():
    near = brightening_mag(DARK, 0.0, 25.0, 50.0, 45.0)
    far = brightening_mag(DARK, 0.0, 140.0, 50.0, 45.0)
    assert near > far > 0


def test_moon_altitude_matters():
    high = brightening_mag(DARK, 0.0, 60.0, 70.0, 45.0)
    low = brightening_mag(DARK, 0.0, 60.0, 5.0, 45.0)
    assert high > low > 0


def test_vectorized_over_a_grid():
    sep = np.linspace(20, 160, 25)
    moon_alt = np.linspace(-10, 70, 25)
    target_alt = np.full(25, 50.0)
    out = brightening_mag(DARK, 30.0, sep, moon_alt, target_alt)
    assert out.shape == (25,)
    assert np.all(out >= 0)
    assert np.all(out[moon_alt <= 0] == 0)


def test_brightening_matches_reference_scale():
    # K&S: a full moon ~90 deg away at moderate altitude under a dark sky
    # lands the sky around 19 mag/arcsec^2 (a couple of magnitudes lost).
    combined = sky_brightness_with_moon(21.9, 0.0, 90.0, 45.0, 45.0)
    assert 18.0 < combined < 20.5
