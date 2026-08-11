"""Night ephemeris: darkness window, target altitude tracks, moon geometry.

Everything is computed on a fixed time grid over one night by direct
sampling (robust at all latitudes/seasons, no special-casing of nights
where astronomical darkness never arrives — we fall back to nautical or
civil darkness automatically).
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body, get_sun
from astropy.time import Time
from astropy.utils import iers

# Never hit the network for Earth-rotation data; bundled tables are fine
# for arcsecond-level planning.
iers.conf.auto_download = False

GRID_STEP_MIN = 6  # sampling step across the night


@dataclass
class NightPlanContext:
    location: EarthLocation
    times: Time                      # grid of sample times (UTC)
    dark: np.ndarray                 # bool mask: sky is dark at these samples
    darkness_kind: str               # astronomical / nautical / civil / none
    moon_alt_deg: np.ndarray
    moon_coord: SkyCoord             # moon position at each sample
    moon_illumination: float         # 0..1 at the middle of the night
    moon_phase_angle_deg: float      # 0 = full, 180 = new
    step_hours: float = field(default=GRID_STEP_MIN / 60.0)

    @property
    def dark_hours(self) -> float:
        return float(self.dark.sum()) * self.step_hours

    @property
    def dark_start(self) -> Time | None:
        idx = np.flatnonzero(self.dark)
        return self.times[idx[0]] if idx.size else None

    @property
    def dark_end(self) -> Time | None:
        idx = np.flatnonzero(self.dark)
        return self.times[idx[-1]] if idx.size else None


def moon_phase_angle(t: Time) -> float:
    """Sun-moon-Earth phase angle in degrees (0 = full, 180 = new)."""
    sun = get_sun(t)
    moon = get_body("moon", t)
    elongation = sun.separation(moon)
    i = np.arctan2(
        sun.distance * np.sin(elongation),
        moon.distance - sun.distance * np.cos(elongation),
    )
    return float(i.to(u.deg).value)


def moon_illumination_fraction(t: Time) -> float:
    """Illuminated fraction of the moon's disk (0=new, 1=full)."""
    return float((1 + np.cos(np.radians(moon_phase_angle(t)))) / 2)


def build_night(date_iso: str, lat_deg: float, lon_deg: float, elevation_m: float = 0.0) -> NightPlanContext:
    """Build the ephemeris grid for the night starting on `date_iso` (local).

    The grid runs from local solar noon on `date_iso` to noon the next day,
    so the whole night is inside it regardless of timezone.
    """
    location = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=elevation_m * u.m)
    # Local solar noon in UTC: 12h minus longitude/15.
    start = Time(f"{date_iso} 12:00:00") - (lon_deg / 15.0) * u.hour
    n_steps = int(24 * 60 / GRID_STEP_MIN) + 1
    times = start + np.arange(n_steps) * GRID_STEP_MIN * u.min

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # IERS age warnings only
        frame = AltAz(obstime=times, location=location)
        sun_alt = get_sun(times).transform_to(frame).alt.deg
        moon_altaz = get_body("moon", times, location=location)
        moon_alt = moon_altaz.transform_to(frame).alt.deg

    dark = sun_alt < -18.0
    kind = "astronomical"
    if not dark.any():
        dark, kind = sun_alt < -12.0, "nautical"
    if not dark.any():
        dark, kind = sun_alt < -6.0, "civil"
    if not dark.any():
        kind = "none"

    mid = times[len(times) // 2]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        phase = moon_phase_angle(mid)
    illum = float((1 + np.cos(np.radians(phase))) / 2)

    return NightPlanContext(
        location=location,
        times=times,
        dark=dark,
        darkness_kind=kind,
        moon_alt_deg=moon_alt,
        moon_coord=moon_altaz,
        moon_illumination=illum,
        moon_phase_angle_deg=phase,
    )


def target_track(ctx: NightPlanContext, ra_deg: float, dec_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """(altitude_deg, moon_separation_deg) for a target across the night grid."""
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        frame = AltAz(obstime=ctx.times, location=ctx.location)
        alt = coord.transform_to(frame).alt.deg
        # Order matters here, and getting it wrong is silent. The moon's GCRS
        # coordinate carries a distance, so `coord.separation(moon)` converts
        # the moon to ICRS *as a nearby object*: it reports where the moon
        # would be seen from the solar-system barycentre, which is tens of
        # degrees from where it is in our sky. Asking the moon for its
        # separation from a distance-free star direction keeps the comparison
        # in the observer's frame — it agrees with doing it in AltAz to 1e-9
        # deg, and that equivalence is pinned by a test.
        sep = ctx.moon_coord.separation(coord).deg
    return alt, sep
