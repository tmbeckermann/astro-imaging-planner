"""Sky brightness model: Bortle class -> SQM -> sky electron rate per pixel.

The chain is:
  1. Bortle class maps to an approximate zenith sky brightness in
     mag/arcsec^2 (SQM, V band).
  2. mag/arcsec^2 converts to a photon flux per arcsec^2 using the V-band
     zero point (a mag-0 star delivers ~8.8e5 photons/s/cm^2 through V).
  3. Multiply by telescope aperture area, the sky area one pixel sees
     (pixel scale squared), QE, optics transmission, and the filter's
     bandwidth factor to get sky electrons per pixel per second.

This is the quantity Robin Glover's optimal-sub-exposure model needs.
"""

import math

from .filters import Filter

# Approximate zenith SQM (mag/arcsec^2) per Bortle class.
BORTLE_SQM: dict[int, float] = {
    1: 21.9,
    2: 21.8,
    3: 21.6,
    4: 21.1,
    5: 20.5,
    6: 19.5,
    7: 18.8,
    8: 18.0,
    9: 17.0,
}

# Photons/s/cm^2 delivered through the V band by a magnitude-0 source.
MAG0_PHOTON_FLUX_V = 8.79e5

# Default end-to-end optics transmission (mirrors/lens + sensor window).
DEFAULT_TRANSMISSION = 0.85


def sqm_from_bortle(bortle: int) -> float:
    if bortle not in BORTLE_SQM:
        raise ValueError(f"Bortle class must be 1-9, got {bortle}")
    return BORTLE_SQM[bortle]


def sky_photon_flux(sqm: float) -> float:
    """Sky photon flux in photons/s/cm^2/arcsec^2 (V band)."""
    return MAG0_PHOTON_FLUX_V * 10 ** (-0.4 * sqm)


def sky_electron_rate(
    sqm: float,
    aperture_mm: float,
    pixel_scale_arcsec: float,
    qe: float,
    filt: Filter,
    transmission: float = DEFAULT_TRANSMISSION,
) -> float:
    """Sky background rate in electrons per pixel per second."""
    area_cm2 = math.pi * (aperture_mm / 20.0) ** 2
    flux = sky_photon_flux(sqm)
    return (
        flux
        * area_cm2
        * pixel_scale_arcsec**2
        * qe
        * transmission
        * filt.sky_bandwidth_factor
    )
