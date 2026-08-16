"""Best time of year to view and image each Messier object, at a given site.

Visibility across the year is pure geometry — RA/Dec against the site's
latitude and the sun's position through the seasons — so it needs no camera,
filter or moon phase. Imaging advice for a target's best month uses the
dark-sky (moonless) rate rather than that specific sample date's actual moon
phase: the 15th of a given month has no more claim to a "typical" lunar phase
than any other day, so showing one arbitrary night's moon cost here would be
noise, not information.
"""

import re
from dataclasses import dataclass

from .catalog import Target, load_targets
from .ephemeris import build_night, target_track

MIN_ALT_DEG = 30.0
MESSIER_ID = re.compile(r"M\d+")


@dataclass(frozen=True)
class MonthVisibility:
    month: int  # 1-12
    usable_hours: float  # hours above min_alt_deg during darkness
    max_alt_deg: float
    dark_hours: float


def messier_targets(targets: list[Target] | None = None) -> list[Target]:
    """The catalog subset Messier himself catalogued, sorted M1, M2, M3..."""
    pool = targets if targets is not None else load_targets()
    return sorted(
        (t for t in pool if MESSIER_ID.fullmatch(t.id)),
        key=lambda t: int(t.id[1:]),
    )


def monthly_visibility(
    target: Target, lat: float, lon: float, ref_year: int, min_alt_deg: float = MIN_ALT_DEG
) -> list[MonthVisibility]:
    """Usable hours above `min_alt_deg` during darkness, for each month of `ref_year`.

    Samples the 15th of each month — sidereal drift over a year is under half
    a degree, well inside the altitude floor's own margin, so one date per
    month resolves the seasonal cycle without needing the whole calendar.
    """
    months = []
    for m in range(1, 13):
        date_iso = f"{ref_year}-{m:02d}-15"
        ctx = build_night(date_iso, lat, lon)
        if ctx.darkness_kind == "none":
            months.append(MonthVisibility(m, 0.0, -90.0, ctx.dark_hours))
            continue
        alt, _ = target_track(ctx, target.ra_deg, target.dec_deg)
        usable = ctx.dark & (alt >= min_alt_deg)
        months.append(MonthVisibility(
            month=m,
            usable_hours=float(usable.sum()) * ctx.step_hours,
            max_alt_deg=float(alt.max()),
            dark_hours=ctx.dark_hours,
        ))
    return months


def best_month(months: list[MonthVisibility]) -> MonthVisibility:
    """Highest usable-hours month; ties broken by peak altitude."""
    return max(months, key=lambda mv: (mv.usable_hours, mv.max_alt_deg))
