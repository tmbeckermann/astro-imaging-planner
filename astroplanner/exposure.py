"""Optimal sub-exposure length, after Robin Glover's SharpCap analysis.

Stacked-image noise per unit time is sqrt(read_noise^2 + sky_rate * t) per
sub. Longer subs dilute the fixed per-sub read noise until sky shot noise
dominates ("sky-limited"). Requiring that total stack noise be no more than
E percent worse than an ideal zero-read-noise camera gives:

    t_optimal = R^2 / (((1 + E/100)^2 - 1) * P)

where R is read noise in electrons and P the sky rate in e-/pixel/s.
The default E = 5% matches Glover's recommendation; the equivalent "swamp
factor" (sky signal / read noise variance) is 1/((1+E/100)^2 - 1) ~ 9.8.
"""

from dataclasses import dataclass

# Common sub lengths (seconds) most capture software offers.
STANDARD_SUBS = [5, 10, 15, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200]


@dataclass(frozen=True)
class ExposureResult:
    optimal_s: float          # exact optimum from the formula
    recommended_s: int        # nearest standard sub length (rounded up)
    sky_e_per_s: float        # sky background rate used
    read_noise_e: float
    noise_increase_pct: float
    swamp_factor: float       # sky electrons per sub / read noise variance


def optimal_sub_exposure(
    read_noise_e: float,
    sky_e_per_s: float,
    noise_increase_pct: float = 5.0,
    max_sub_s: float = 1200.0,
) -> ExposureResult:
    if sky_e_per_s <= 0:
        raise ValueError("sky electron rate must be positive")
    k = (1.0 + noise_increase_pct / 100.0) ** 2 - 1.0
    t = read_noise_e**2 / (k * sky_e_per_s)
    t_capped = min(t, max_sub_s)
    recommended = next((s for s in STANDARD_SUBS if s >= t_capped), STANDARD_SUBS[-1])
    return ExposureResult(
        optimal_s=t,
        recommended_s=recommended,
        sky_e_per_s=sky_e_per_s,
        read_noise_e=read_noise_e,
        noise_increase_pct=noise_increase_pct,
        swamp_factor=1.0 / k,
    )


def stack_noise_penalty(read_noise_e: float, sky_e_per_s: float, sub_s: float) -> float:
    """Percent extra stack noise vs an ideal camera, for a given sub length."""
    sky_e = sky_e_per_s * sub_s
    return ((read_noise_e**2 + sky_e) / sky_e) ** 0.5 * 100.0 - 100.0
