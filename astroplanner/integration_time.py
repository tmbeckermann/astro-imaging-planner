"""How much total integration time is enough, and when more stops helping.

There is no hard stopping point in the noise itself: stacked SNR grows as
sqrt(total time) for as long as you keep adding subs, forever. What changes is
how much each additional hour buys you, which shrinks the longer you've
already been shooting.

One result worth stating plainly, because it is easy to assume otherwise: for
a fixed sub length, signal grows exactly linearly with total time and noise
grows as exactly sqrt(total time) — regardless of how that noise splits
between target shot noise, sky shot noise and read noise. So the *shape* of
the diminishing-returns curve (percent SNR gained by one more hour) is a
universal sqrt(T) constant, the same for every target, filter, site and rig,
as long as the sub length does not change mid-session. `marginal_gain_pct` and
`elbow_hours` reflect that: they take no target/sky/read-noise arguments,
because none of those change the answer.

What *does* depend on the target is the absolute SNR value at any given hour —
that needs the target's own signal rate (see `sky.target_electron_rate`,
`catalog.Target.surface_brightness_mag`), which is what `snr_at_time` and
`diminishing_returns_table` are for.

The SNR model is the standard CCD equation, without dark current (not modelled
elsewhere in this package) or calibration-residual noise (gradients, flat
errors, amp glow) — the real floor those introduce cannot be predicted, only
measured from an actual stack.
"""

import math
from dataclasses import dataclass

DEFAULT_THRESHOLD_PCT = 5.0
DEFAULT_STEP_S = 3600.0
DEFAULT_MAX_HOURS = 48.0


def snr_at_time(
    target_e_per_s: float,
    sky_e_per_s: float,
    read_noise_e: float,
    total_s: float,
    sub_s: float,
) -> float:
    """Stacked SNR after `total_s` seconds of `sub_s`-second subs."""
    if total_s <= 0 or sub_s <= 0:
        return 0.0
    n_subs = total_s / sub_s
    signal = target_e_per_s * total_s
    noise_var = (target_e_per_s + sky_e_per_s) * total_s + n_subs * read_noise_e**2
    return signal / math.sqrt(noise_var) if noise_var > 0 else 0.0


def marginal_gain_pct(total_s: float, step_s: float = DEFAULT_STEP_S) -> float:
    """% SNR gain from one more `step_s` of integration, on top of `total_s`.

    Closed form: SNR(T) is exactly proportional to sqrt(T) for fixed sub
    length (see module docstring), so SNR(T+dt)/SNR(T) = sqrt((T+dt)/T) —
    independent of target brightness, sky rate, read noise and sub length
    alike. That cancellation is the whole point of exposing this separately
    from `snr_at_time` rather than folding it back into the same signature.
    """
    if total_s <= 0:
        return float("inf")
    return (math.sqrt((total_s + step_s) / total_s) - 1.0) * 100.0


def elbow_hours(
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    step_s: float = DEFAULT_STEP_S,
    max_hours: float = DEFAULT_MAX_HOURS,
) -> float:
    """Total hours at which one more hour buys less than `threshold_pct` more SNR.

    Closed form from `marginal_gain_pct`: solve sqrt((T+dt)/T) - 1 = p/100 for
    T, giving T = dt / ((1 + p/100)^2 - 1). Universal for the reason given in
    the module docstring — the same ~10h applies at Bortle 2 or Bortle 9, on a
    3rd-magnitude nebula or a 14th-magnitude galaxy, on a 50mm smart scope or
    a 10-inch RC, provided the sub length stays fixed through the session.
    """
    k = (1.0 + threshold_pct / 100.0) ** 2 - 1.0
    hours = (step_s / k) / 3600.0
    return min(hours, max_hours)


@dataclass(frozen=True)
class IntegrationPoint:
    hours: float
    snr: float
    next_hour_gain_pct: float  # % SNR gained by the hour after this one


def diminishing_returns_table(
    target_e_per_s: float,
    sky_e_per_s: float,
    read_noise_e: float,
    sub_s: float,
    hours: tuple[float, ...] = (1, 2, 4, 8, 16, 24),
) -> list[IntegrationPoint]:
    """SNR at each milestone — this is where target brightness actually shows up.

    `next_hour_gain_pct` is the same at a given hour count for every row of
    every target's table; `snr` is not, and is the number worth comparing
    target to target.
    """
    return [
        IntegrationPoint(
            hours=h,
            snr=snr_at_time(target_e_per_s, sky_e_per_s, read_noise_e, h * 3600.0, sub_s),
            next_hour_gain_pct=marginal_gain_pct(h * 3600.0),
        )
        for h in hours
    ]
