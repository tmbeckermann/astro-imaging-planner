"""Rank catalog targets for one night at one site with one rig.

Score = usable dark hours above the altitude floor
        x mean altitude quality while usable
        x (1 - moonlight penalty)
        x field-of-view fit.

The moonlight penalty combines moon illumination, how much of the target's
usable window the moon is actually up, angular separation, and how
moon-susceptible the chosen filter is. Line-emission targets shot through a
line filter barely care about the moon; broadband galaxies care a lot.
"""

from dataclasses import dataclass

import numpy as np

from .catalog import Target, load_targets
from .ephemeris import NightPlanContext, target_track
from .exposure import ExposureResult, optimal_sub_exposure
from .filters import FILTERS, Filter
from .sensors import Camera
from .sky import sky_electron_rate, sqm_from_bortle

MIN_ALT_DEG = 30.0


@dataclass
class RankedTarget:
    target: Target
    score: float
    usable_hours: float
    max_alt_deg: float
    mean_moon_sep_deg: float
    moon_penalty: float
    fov_fit: float
    best_window: tuple[str, str] | None   # UTC hh:mm strings
    suggested_filter: Filter
    exposure: ExposureResult


def fov_fit_score(target_size_arcmin: float, fov_arcmin: tuple[float, float]) -> float:
    short_side = min(fov_arcmin)
    ratio = target_size_arcmin / short_side
    if ratio < 0.1:          # tiny in the frame
        return max(ratio / 0.1, 0.15)
    if ratio <= 0.9:         # comfortable framing
        return 1.0
    return max(0.9 / ratio, 0.15)  # spills out of frame


def suggest_filter(target: Target, ctx: NightPlanContext, bortle: int, available: list[Filter]) -> Filter:
    """Pick the sensible filter: line filter for line emitters under moon or
    heavy light pollution, otherwise the most broadband option available."""
    line_filters = [f for f in available if f.line_filter]
    broad = [f for f in available if not f.line_filter]
    broadest = max(broad, key=lambda f: f.sky_bandwidth_factor) if broad else available[0]
    if target.line_emitter and line_filters and (ctx.moon_illumination > 0.3 or bortle >= 6):
        # Prefer duoband (widest line filter) for one-shot-color convenience.
        return max(line_filters, key=lambda f: f.sky_bandwidth_factor)
    return broadest


def rank_targets(
    ctx: NightPlanContext,
    camera: Camera,
    focal_length_mm: float,
    aperture_mm: float,
    bortle: int,
    available_filters: list[str] | None = None,
    min_alt_deg: float = MIN_ALT_DEG,
    targets: list[Target] | None = None,
) -> list[RankedTarget]:
    targets = targets if targets is not None else load_targets()
    filters = [FILTERS[k] for k in (available_filters or list(FILTERS))]
    fov = camera.fov_arcmin(focal_length_mm)
    pixel_scale = camera.pixel_scale(focal_length_mm)
    sqm = sqm_from_bortle(bortle)

    ranked: list[RankedTarget] = []
    for t in targets:
        alt, moon_sep = target_track(ctx, t.ra_deg, t.dec_deg)
        usable = ctx.dark & (alt >= min_alt_deg)
        usable_hours = float(usable.sum()) * ctx.step_hours
        if usable_hours <= 0:
            continue

        alt_quality = float(np.mean(np.sin(np.radians(alt[usable]))))
        filt = suggest_filter(t, ctx, bortle, filters)

        moon_up = usable & (ctx.moon_alt_deg > 0)
        moon_up_frac = float(moon_up.sum()) / float(usable.sum())
        if moon_up.any():
            sep_while_up = float(np.mean(moon_sep[moon_up]))
            proximity = max(0.0, 1.0 - sep_while_up / 150.0)
        else:
            sep_while_up = float(np.mean(moon_sep[usable]))
            proximity = 0.0
        moon_penalty = min(
            0.95,
            ctx.moon_illumination * moon_up_frac * proximity * filt.moon_susceptibility * 2.0,
        )

        fov_fit = fov_fit_score(t.size_arcmin, fov)
        score = usable_hours * alt_quality * (1.0 - moon_penalty) * fov_fit

        idx = np.flatnonzero(usable)
        window = (
            ctx.times[idx[0]].strftime("%H:%M"),
            ctx.times[idx[-1]].strftime("%H:%M"),
        )
        sky_rate = sky_electron_rate(sqm, aperture_mm, pixel_scale, camera.qe, filt)
        exp = optimal_sub_exposure(camera.read_noise_e, sky_rate)

        ranked.append(
            RankedTarget(
                target=t,
                score=score,
                usable_hours=usable_hours,
                max_alt_deg=float(alt.max()),
                mean_moon_sep_deg=sep_while_up,
                moon_penalty=moon_penalty,
                fov_fit=fov_fit,
                best_window=window,
                suggested_filter=filt,
                exposure=exp,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
