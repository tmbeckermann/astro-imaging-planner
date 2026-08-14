"""Unit presentation: imperial or metric, and local clock time.

Only presentation. Every calculation in this package stays in millimetres,
degrees and UTC — a unit system is a thing you read, not a thing you compute
in, and mixing the two is how sign errors get into ephemerides.

Note which quantities are *not* converted. Focal length, pixel scale and field
of view have no imperial form in practice: nobody writes a 336-inch focal
length or arcseconds-per-inch. Aperture is the exception, because telescopes
genuinely are sold as 8-inch and 80 mm in the same shop, so it gets both.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

METRIC, IMPERIAL = "metric", "imperial"
UNIT_SYSTEMS = (IMPERIAL, METRIC)

# Central time: where this planner's author observes from.
DEFAULT_TZ = "America/Chicago"

MM_PER_INCH = 25.4
FEET_PER_METRE = 3.280839895


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(
            f"Unknown timezone '{name}'. Use an IANA name such as America/Chicago, "
            f"America/New_York, Europe/London, or UTC."
        ) from None


def to_local(utc_dt: datetime, zone: ZoneInfo) -> datetime:
    """Attach UTC to a naive astropy datetime, then move it to `zone`."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(zone)


def local_hhmm(utc_dt: datetime, zone: ZoneInfo) -> str:
    return to_local(utc_dt, zone).strftime("%H:%M")


def zone_abbrev(utc_dt: datetime, zone: ZoneInfo) -> str:
    """CDT / CST / GMT — whichever is in force at that instant."""
    return to_local(utc_dt, zone).strftime("%Z")


def format_elevation(metres: float, units: str = IMPERIAL) -> str:
    if units == IMPERIAL:
        return f"{metres * FEET_PER_METRE:,.0f} ft"
    return f"{metres:,.0f} m"


# Below about an inch, nobody quotes a telescope in inches — a camera lens's
# entrance pupil is a millimetre figure in every catalogue that prints one.
SMALLEST_APERTURE_IN_INCHES_MM = 25.4


def format_aperture(mm: float, units: str = IMPERIAL) -> str:
    """Imperial shows both, because telescopes are sold both ways."""
    if units == IMPERIAL and mm >= SMALLEST_APERTURE_IN_INCHES_MM:
        return f'{mm / MM_PER_INCH:.1f}" ({mm:.0f} mm)'
    return f"{mm:.1f} mm" if mm < 10 else f"{mm:.0f} mm"


def format_focal_length(mm: float) -> str:
    """A 6.7 mm wide-angle lens is not a 7 mm one; keep the decimal where it counts."""
    return f"{mm:.1f} mm" if mm < 10 else f"{mm:.0f} mm"


def format_fov(width_arcmin: float, height_arcmin: float) -> str:
    """Arcminutes for a telescope, degrees once the field is constellation-sized."""
    if max(width_arcmin, height_arcmin) >= 120:
        return f"{width_arcmin / 60:.1f}° x {height_arcmin / 60:.1f}°"
    return f"{width_arcmin:.0f}' x {height_arcmin:.0f}'"
