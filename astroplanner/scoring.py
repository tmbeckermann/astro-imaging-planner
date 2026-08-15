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

Alongside the SNR-optimal filter, every target carries advice in the three
modes people actually own hardware for — full spectrum, visible (UV/IR cut),
duo-band — see `recommend_mode`.
"""

from dataclasses import dataclass

import numpy as np

from .catalog import Target, load_targets
from .ephemeris import NightPlanContext, target_track
from .exposure import ExposureResult, optimal_sub_exposure
from .filters import (
    FILTERS,
    MODE_KEYS,
    Filter,
    mode_available,
    mode_filter,
    mode_label,
)
from .moon import brightening_mag, sky_brightness_with_moon
from .sensors import Camera
from .sky import sky_electron_rate, sqm_from_bortle

MIN_ALT_DEG = 30.0

# How much more SNR full spectrum must deliver before it is worth recommending
# over the colour-correct visible train. See `recommend_mode`.
FULL_SPECTRUM_MARGIN = 1.15


@dataclass(frozen=True)
class ModeScore:
    """What one imaging mode would achieve on one target tonight."""
    mode: str                # full / visible / line
    label: str               # what to call it for this camera
    filter_key: str          # the concrete filter the mode resolves to
    available: bool          # False = this camera or this filter bag can't do it
    sky_quality: float       # SNR, 1.0 = visible train under a moonless sky here
    sky_e_per_s: float
    recommended_sub_s: int
    note: str = ""
    sub_capped: bool = False   # the instrument cannot expose as long as it wants to


@dataclass(frozen=True)
class ModeAdvice:
    recommended: str
    reason: str
    scores: dict[str, ModeScore]
    caution: str = ""

    @property
    def best(self) -> ModeScore:
        return self.scores[self.recommended]


def recommend_mode(
    line_emitter: bool,
    camera: Camera,
    rate_for,
    reference_snr: float,
    allowed_filter_keys: set[str] | None = None,
    max_sub_s: float = 1200.0,
) -> ModeAdvice:
    """Pick between full spectrum, visible (UV/IR cut), and duo-band.

    The three modes are not three points on one axis, so this is not a plain
    argmax over SNR:

    * For an emission target a line filter is not a close call. It passes the
      nebula's Ha/OIII while cutting continuum sky ~20-40x, so it wins by a
      factor of several against either broadband mode, at any Bortle class and
      with or without the moon. (The win is site-independent under a flat sky
      model, which is exactly why it is worth owning one filter rather than
      driving somewhere darker.)

    * Between the two broadband modes the model says something more
      interesting: it is close to a tie. Dropping the UV/IR cut opens roughly
      1.6x more sky but only ~1.3x more target, because the near-IR is where
      the OH airglow bands live and most deep-sky continuum is not especially
      NIR-bright. Net, full spectrum is worth about 2% in SNR — and costs true
      star colour and tight stars in any refractor that is not corrected out
      to 1000 nm. So visible wins ties, and full spectrum has to clear
      FULL_SPECTRUM_MARGIN to be recommended. That reproduces the standard
      field advice (always put a UV/IR cut on a modified camera) from the
      photon budget rather than from folklore.
    """
    scores: dict[str, ModeScore] = {}
    for mode in MODE_KEYS:
        filt = mode_filter(mode, camera, allowed_filter_keys)
        allowed = allowed_filter_keys is None or filt.key in allowed_filter_keys
        available = mode_available(mode, camera) and allowed
        rate = rate_for(filt)
        snr = snr_quality(filt, line_emitter, rate, camera)
        exposure = optimal_sub_exposure(camera.read_noise_e, rate, max_sub_s=max_sub_s)
        note = ""
        if not mode_available(mode, camera):
            note = "needs a camera without a built-in IR-cut filter"
        elif not allowed:
            note = "not fitted to this rig"
        scores[mode] = ModeScore(
            mode=mode,
            label=mode_label(mode, camera, filt),
            filter_key=filt.key,
            available=available,
            sky_quality=float(snr / reference_snr),
            sky_e_per_s=float(rate),
            recommended_sub_s=exposure.recommended_s,
            note=note,
            sub_capped=exposure.optimal_s > max_sub_s,
        )

    usable = {k: v for k, v in scores.items() if v.available}
    if not usable:  # every mode ruled out by --filters
        return ModeAdvice("visible", "no listed filter can shoot this target", scores)

    caution = ""
    if line_emitter and "line" in usable:
        pick = "line"
        ratio = scores["line"].sky_quality / max(scores["visible"].sky_quality, 1e-9)
        reason = (
            f"line emitter: {scores['line'].label} delivers {ratio:.1f}x the SNR "
            f"of a visible train here"
        )
        if camera.ha_transmission < 0.5:
            caution = (
                f"this camera passes only {camera.ha_transmission:.0%} of Ha, so the result "
                f"will be OIII-dominated — modifying the camera buys more than the filter does"
            )
    else:
        best_key = max(usable, key=lambda k: usable[k].sky_quality)
        vis = usable.get("visible")
        full = usable.get("full")
        if best_key == "full" and vis is not None:
            edge = full.sky_quality / max(vis.sky_quality, 1e-9)
            if edge < FULL_SPECTRUM_MARGIN:
                pick = "visible"
                reason = (
                    f"broadband target: full spectrum is only {edge - 1:+.0%} SNR, "
                    f"not worth the colour cast and IR star bloat"
                )
            else:
                pick = "full"
                reason = f"broadband target: full spectrum is worth {edge - 1:+.0%} SNR here"
        else:
            pick = best_key
            reason = "highest SNR of the modes available"
            if not line_emitter and best_key == "visible":
                reason = "broadband target: the colour-correct train is also the deepest here"
            elif not line_emitter and best_key == "full" and vis is None:
                reason = ("broadband target, and this rig has no UV/IR cut — so broadband "
                          "means full spectrum, with the star bloat and colour cast that brings")
            elif line_emitter and best_key != "line":
                reason = "line emitter, but no line filter available — broadband it is"
        if not line_emitter and not mode_available("full", camera):
            caution = "full spectrum unavailable: this camera's IR-cut filter is built in"

    return ModeAdvice(pick, reason, scores, caution)


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
    window_idx: tuple[int, int] | None    # grid indices, so callers can localise
    suggested_filter: Filter
    exposure: ExposureResult
    dark_sky_rate: float         # e-/px/s with no moon, for comparison
    mode_advice: ModeAdvice | None = None   # full spectrum / visible / duo-band


def fov_fit_score(target_size_arcmin: float, fov_arcmin: tuple[float, float]) -> float:
    short_side = min(fov_arcmin)
    ratio = target_size_arcmin / short_side
    if ratio < 0.1:          # tiny in the frame
        return max(ratio / 0.1, 0.15)
    if ratio <= 0.9:         # comfortable framing
        return 1.0
    return max(0.9 / ratio, 0.15)  # spills out of frame


def snr_quality(
    filt: Filter, line_emitter: bool, sky_e_per_s: float, camera: Camera | None = None
) -> float:
    """Relative background-limited SNR: target signal / sqrt(sky noise).

    This is the figure of merit the filter choice maximizes. It is a
    *relative* number — only ratios between filters/conditions are meaningful.
    """
    return filt.signal_factor(line_emitter, camera) / np.sqrt(sky_e_per_s)


def best_filter(
    line_emitter: bool,
    available: list[Filter],
    rate_for: "callable",
    camera: Camera | None = None,
) -> tuple[Filter, float]:
    """Pick the filter with the highest SNR, given a sky-rate function.

    Note this optimizes SNR alone: it does not know that a broadband filter
    also captures colour in one shot, or that narrowband needs far more total
    integration time. Restrict `--filters` to what you actually want to use.
    """
    scored = [(f, snr_quality(f, line_emitter, rate_for(f), camera)) for f in available]
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
    max_sub_s: float = 1200.0,
    dark_sqm: float | None = None,
) -> list[RankedTarget]:
    targets = targets if targets is not None else load_targets()
    filters = [FILTERS[k] for k in (available_filters or list(FILTERS))]
    fov = camera.fov_arcmin(focal_length_mm)
    pixel_scale = camera.pixel_scale(focal_length_mm)
    # A number off a light-pollution atlas or a meter beats a class: Bortle is
    # a nine-step ladder over a continuum, and one step is worth ~0.7 mag.
    dark_sqm = sqm_from_bortle(bortle) if dark_sqm is None else float(dark_sqm)

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
        filt, moonlit_quality = best_filter(t.line_emitter, filters, moonlit_rate, camera)
        _, dark_quality = best_filter(t.line_emitter, filters, dark_rate_for, camera)
        mean_rate = moonlit_rate(filt)
        dark_rate = dark_rate_for(filt)

        moon_penalty = float(np.clip(1.0 - moonlit_quality / dark_quality, 0.0, 0.95))

        # Absolute achievable SNR, in units of "unfiltered under this site's
        # moonless sky". A narrowband line target can exceed 1.0 even under a
        # full moon; that is precisely why it stays worth shooting.
        reference = snr_quality(FILTERS["none"], False, dark_rate_for(FILTERS["none"]))
        advice = recommend_mode(
            t.line_emitter,
            camera,
            moonlit_rate,
            reference,
            {f.key for f in filters} if available_filters else None,
            max_sub_s,
        )
        # Rank on what you would actually shoot — the recommended mode — not on
        # the SNR-optimal filter in the abstract. Otherwise a one-shot-colour
        # rig gets ranked on 3 nm mono narrowband it cannot sensibly use.
        sky_quality = advice.best.sky_quality

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
        window_idx = (int(idx[0]), int(idx[-1]))
        exp = optimal_sub_exposure(camera.read_noise_e, mean_rate, max_sub_s=max_sub_s)

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
                window_idx=window_idx,
                suggested_filter=filt,
                exposure=exp,
                dark_sky_rate=dark_rate,
                mode_advice=advice,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
