"""Rank catalog targets for one night at one site with one rig.

Score = usable dark hours above the altitude floor
        x mean altitude quality while usable
        x achievable sky quality (SNR, including the moon's cost)
        x field-of-view fit.

Moonlight is evaluated physically (Krisciunas & Schaefer): at every sample in
the target's usable window we compute how much the moon brightens the sky at
that target's position, and convert that to a sky electron rate per filter.

One consequence is worth stating, because it is easy to get wrong: under a
flat-spectrum sky model the moon's *fractional* SNR cost is the same whatever
filter you use. Moonlight and light-pollution skyglow are both continuum, so
a filter attenuates both equally and the ratio cancels. Narrowband does not
reduce the moon's relative bite.

What narrowband actually buys is *absolute* SNR: it passes an emission
nebula's line flux while cutting continuum sky ~40x, so an Ha sub under a
full moon can beat an unfiltered sub under a dark sky. That is captured by
`sky_quality` (1.0 = unfiltered under this site's moonless sky), which is
what the ranking multiplies in — so on a bright night emission targets rise
and galaxies sink, from physics rather than a special case.
"""

from dataclasses import dataclass

import numpy as np

from .catalog import Target, load_targets
from .ephemeris import NightPlanContext, target_track
from .exposure import ExposureResult, optimal_sub_exposure
from .filters import FILTERS, Filter
from .moon import brightening_mag, sky_brightness_with_moon
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
    moon_penalty: float          # 0..0.95, fractional SNR loss to moonlight
    moon_brightening_mag: float  # mag/arcsec^2 the moon costs, mean over window
    sky_quality: float           # achieved SNR vs unfiltered-at-dark-sky = 1.0
    fov_fit: float
    best_window: tuple[str, str] | None   # UTC hh:mm strings
    suggested_filter: Filter
    exposure: ExposureResult
    dark_sky_rate: float         # e-/px/s with no moon, for comparison


def fov_fit_score(target_size_arcmin: float, fov_arcmin: tuple[float, float]) -> float:
    short_side = min(fov_arcmin)
    ratio = target_size_arcmin / short_side
    if ratio < 0.1:          # tiny in the frame
        return max(ratio / 0.1, 0.15)
    if ratio <= 0.9:         # comfortable framing
        return 1.0
    return max(0.9 / ratio, 0.15)  # spills out of frame


def snr_quality(filt: Filter, line_emitter: bool, sky_e_per_s: float) -> float:
    """Relative background-limited SNR: target signal / sqrt(sky noise).

    This is the figure of merit the filter choice maximizes. It is a
    *relative* number — only ratios between filters/conditions are meaningful.
    """
    return filt.signal_factor(line_emitter) / np.sqrt(sky_e_per_s)


def best_filter(
    line_emitter: bool,
    available: list[Filter],
    rate_for: "callable",
) -> tuple[Filter, float]:
    """Pick the filter with the highest SNR, given a sky-rate function.

    Note this optimizes SNR alone: it does not know that a broadband filter
    also captures colour in one shot, or that narrowband needs far more total
    integration time. Restrict `--filters` to what you actually want to use.
    """
    scored = [(f, snr_quality(f, line_emitter, rate_for(f))) for f in available]
    return max(scored, key=lambda pair: pair[1])


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
    dark_sqm = sqm_from_bortle(bortle)

    ranked: list[RankedTarget] = []
    for t in targets:
        alt, moon_sep = target_track(ctx, t.ra_deg, t.dec_deg)
        usable = ctx.dark & (alt >= min_alt_deg)
        usable_hours = float(usable.sum()) * ctx.step_hours
        if usable_hours <= 0:
            continue

        alt_quality = float(np.mean(np.sin(np.radians(alt[usable]))))

        # Moonlit sky brightness at this target's position, sample by sample.
        moonlit_sqm = np.atleast_1d(sky_brightness_with_moon(
            dark_sqm,
            ctx.moon_phase_angle_deg,
            moon_sep[usable],
            ctx.moon_alt_deg[usable],
            alt[usable],
        ))
        mean_brightening = float(np.mean(
            brightening_mag(
                dark_sqm,
                ctx.moon_phase_angle_deg,
                moon_sep[usable],
                ctx.moon_alt_deg[usable],
                alt[usable],
            )
        ))

        def moonlit_rate(f: Filter, _sqm=moonlit_sqm) -> float:
            return float(np.mean([
                sky_electron_rate(s, aperture_mm, pixel_scale, camera.qe, f)
                for s in _sqm
            ]))

        def dark_rate_for(f: Filter) -> float:
            return sky_electron_rate(dark_sqm, aperture_mm, pixel_scale, camera.qe, f)

        # Choose the filter that maximises SNR under tonight's actual sky,
        # and measure the moon's cost against the best moonless alternative.
        filt, moonlit_quality = best_filter(t.line_emitter, filters, moonlit_rate)
        _, dark_quality = best_filter(t.line_emitter, filters, dark_rate_for)
        mean_rate = moonlit_rate(filt)
        dark_rate = dark_rate_for(filt)

        moon_penalty = float(np.clip(1.0 - moonlit_quality / dark_quality, 0.0, 0.95))

        # Absolute achievable SNR, in units of "unfiltered under this site's
        # moonless sky". A narrowband line target can exceed 1.0 even under a
        # full moon; that is precisely why it stays worth shooting.
        reference = snr_quality(FILTERS["none"], False, dark_rate_for(FILTERS["none"]))
        sky_quality = float(moonlit_quality / reference)

        moon_up = usable & (ctx.moon_alt_deg > 0)
        sep_ref = moon_sep[moon_up] if moon_up.any() else moon_sep[usable]
        mean_sep = float(np.mean(sep_ref))

        fov_fit = fov_fit_score(t.size_arcmin, fov)
        # sky_quality is capped at 1.0 for ranking. It measures the gain a
        # filter gives *this* target against its own unfiltered baseline, so
        # 8.5x on a narrowband nebula is not "8.5x prettier than a galaxy" -
        # comparing it raw across targets would bury every broadband object.
        # Capped, it reads as "fraction of a perfect moonless night retained":
        # under a full moon a narrowband nebula holds ~1.0 while a galaxy
        # falls to ~0.3, and on a dark night everything sits at 1.0 so hours,
        # altitude and framing decide.
        score = usable_hours * alt_quality * min(sky_quality, 1.0) * fov_fit

        idx = np.flatnonzero(usable)
        window = (
            ctx.times[idx[0]].strftime("%H:%M"),
            ctx.times[idx[-1]].strftime("%H:%M"),
        )
        exp = optimal_sub_exposure(camera.read_noise_e, mean_rate)

        ranked.append(
            RankedTarget(
                target=t,
                score=score,
                usable_hours=usable_hours,
                max_alt_deg=float(alt.max()),
                mean_moon_sep_deg=mean_sep,
                moon_penalty=moon_penalty,
                moon_brightening_mag=mean_brightening,
                sky_quality=sky_quality,
                fov_fit=fov_fit,
                best_window=window,
                suggested_filter=filt,
                exposure=exp,
                dark_sky_rate=dark_rate,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
