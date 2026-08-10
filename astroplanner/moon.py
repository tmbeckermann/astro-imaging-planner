"""Moonlight sky-brightness model (Krisciunas & Schaefer 1991, PASP 103, 1033).

Moonlight is sunlight scattered by the atmosphere, so how much it degrades a
given target depends on four things: the moon's phase angle, its altitude,
the target's altitude, and the angular separation between them. A full moon
30 deg from your target can brighten the sky by 3+ magnitudes; the same moon
120 deg away costs you far less.

The model returns a surface brightness the same way an SQM reads the sky, so
moonlit and dark-sky contributions can be added in linear flux and handed
straight to the exposure calculator. All functions are numpy-vectorized over
the night grid.
"""

import numpy as np

# V-band atmospheric extinction coefficient, mag/airmass. 0.172 is the
# Krisciunas & Schaefer value for a good dark site; hazier sites scatter
# more moonlight (higher k) but also dim the moon before it scatters.
DEFAULT_EXTINCTION_K = 0.172


def airmass(zenith_distance_deg):
    """Kasten-style airmass valid to the horizon (K&S eq. 3)."""
    z = np.radians(np.asarray(zenith_distance_deg, dtype=float))
    return (1.0 - 0.96 * np.sin(z) ** 2) ** -0.5


def phase_angle_from_illumination(illuminated_fraction: float) -> float:
    """Moon phase angle in degrees (0 = full, 180 = new)."""
    k = float(np.clip(illuminated_fraction, 0.0, 1.0))
    return float(np.degrees(np.arccos(2.0 * k - 1.0)))


def moon_illuminance(phase_angle_deg):
    """Moon illuminance outside the atmosphere (K&S eq. 8), arbitrary units."""
    a = np.abs(np.asarray(phase_angle_deg, dtype=float))
    return 10 ** (-0.4 * (3.84 + 0.026 * a + 4.0e-9 * a**4))


def scattering_function(separation_deg):
    """Atmospheric scattering toward the target (K&S eq. 9).

    Rayleigh scattering dominates at large separations, aerosol (Mie)
    forward-scattering within a few tens of degrees of the moon.
    """
    rho = np.radians(np.asarray(separation_deg, dtype=float))
    rayleigh = 10**5.36 * (1.06 + np.cos(rho) ** 2)
    mie = 10 ** (6.15 - np.degrees(rho) / 40.0)
    return rayleigh + mie


def nanolambert_to_mag(brightness_nl):
    """Convert surface brightness in nanoLamberts to mag/arcsec^2."""
    b = np.maximum(np.asarray(brightness_nl, dtype=float), 1e-12)
    return (20.7233 - np.log(b / 34.08)) / 0.92104


def mag_to_nanolambert(mag_per_arcsec2):
    """Convert surface brightness in mag/arcsec^2 to nanoLamberts."""
    mu = np.asarray(mag_per_arcsec2, dtype=float)
    return 34.08 * np.exp(20.7233 - 0.92104 * mu)


def moon_sky_brightness_nl(
    phase_angle_deg,
    separation_deg,
    moon_alt_deg,
    target_alt_deg,
    k=DEFAULT_EXTINCTION_K,
):
    """Sky brightness added by the moon, in nanoLamberts (K&S eq. 15).

    Zero wherever the moon is below the horizon or the target is not up.
    """
    phase_angle_deg, separation_deg, moon_alt_deg, target_alt_deg = np.broadcast_arrays(
        np.asarray(phase_angle_deg, dtype=float),
        np.asarray(separation_deg, dtype=float),
        np.asarray(moon_alt_deg, dtype=float),
        np.asarray(target_alt_deg, dtype=float),
    )

    x_moon = airmass(90.0 - moon_alt_deg)
    x_target = airmass(90.0 - target_alt_deg)

    b = (
        scattering_function(separation_deg)
        * moon_illuminance(phase_angle_deg)
        * 10 ** (-0.4 * k * x_moon)          # moonlight dimmed on the way in
        * (1.0 - 10 ** (-0.4 * k * x_target))  # fraction scattered toward us
    )
    visible = (moon_alt_deg > 0.0) & (target_alt_deg > 0.0)
    return np.where(visible, b, 0.0)


def sky_brightness_with_moon(
    dark_sqm,
    phase_angle_deg,
    separation_deg,
    moon_alt_deg,
    target_alt_deg,
    k=DEFAULT_EXTINCTION_K,
):
    """Combined dark-sky + moonlight surface brightness, in mag/arcsec^2.

    Brightness adds linearly, magnitudes do not — so both terms are converted
    to nanoLamberts, summed, and converted back.
    """
    b_dark = mag_to_nanolambert(dark_sqm)
    b_moon = moon_sky_brightness_nl(
        phase_angle_deg, separation_deg, moon_alt_deg, target_alt_deg, k
    )
    return nanolambert_to_mag(b_dark + b_moon)


def brightening_mag(
    dark_sqm,
    phase_angle_deg,
    separation_deg,
    moon_alt_deg,
    target_alt_deg,
    k=DEFAULT_EXTINCTION_K,
):
    """How many magnitudes the moon brightens the sky (0 = no effect)."""
    combined = sky_brightness_with_moon(
        dark_sqm, phase_angle_deg, separation_deg, moon_alt_deg, target_alt_deg, k
    )
    return np.asarray(dark_sqm, dtype=float) - combined
