"""Filter database.

sky_bandwidth_factor expresses how much broadband sky glow the filter passes,
relative to the Johnson V band (~88 nm) that the SQM sky-brightness scale is
defined against. A full-visible-spectrum filter passes roughly 3.4x the V-band
flux; a 7 nm narrowband passes ~0.08x. This is a flat-spectrum approximation —
real skyglow is not flat (LEDs, airglow lines), but it is plenty accurate for
choosing a sub length.

moon_susceptibility is a rough "how much does the moon hurt" label, kept for
display only. The planner no longer uses it: scattered moonlight is solar
continuum, so sky_bandwidth_factor already describes how much of it a filter
rejects, and the Krisciunas & Schaefer model in moon.py supplies the rest.
"""

from dataclasses import dataclass


# Sky bandwidth factor of an unfiltered (UV/IR-cut only) imaging train.
# Used as the reference for continuum transmission.
NO_FILTER_SKY_FACTOR = 3.4


@dataclass(frozen=True)
class Filter:
    key: str
    name: str
    sky_bandwidth_factor: float
    moon_susceptibility: float   # display label only; see module docstring
    line_filter: bool            # passes only emission lines (Ha/OIII/SII)
    line_transmission: float = 0.90   # fraction of Ha/OIII line flux passed
    continuum_transmission: float = 1.0  # fraction of broadband target flux passed

    def signal_factor(self, line_emitter: bool) -> float:
        """Fraction of the target's own flux this filter delivers.

        The point a bandwidth-only model misses: a narrowband filter cuts
        continuum skyglow 40x while passing nearly all of an emission
        nebula's line flux. For a galaxy it cuts the target just as hard as
        the sky, which is why narrowband buys nothing on continuum objects.
        """
        if not self.line_filter:
            return self.continuum_transmission
        if line_emitter:
            return self.line_transmission
        return self.sky_bandwidth_factor / NO_FILTER_SKY_FACTOR


FILTERS: dict[str, Filter] = {
    f.key: f
    for f in [
        Filter("none", "No filter / UV-IR cut", 3.4, 1.00, False, continuum_transmission=1.00),
        Filter("cls", "CLS / broadband light-pollution", 1.7, 0.65, False, continuum_transmission=0.85),
        Filter("duoband", "Duo-band (Ha + OIII, ~2x7 nm)", 0.16, 0.25, True, line_transmission=0.90),
        Filter("nb7", "Narrowband 7 nm (Ha or OIII)", 0.08, 0.15, True, line_transmission=0.90),
        Filter("nb3", "Narrowband 3 nm (Ha or OIII)", 0.034, 0.08, True, line_transmission=0.85),
    ]
}


def get_filter(key: str) -> Filter:
    try:
        return FILTERS[key.lower()]
    except KeyError:
        known = ", ".join(sorted(FILTERS))
        raise KeyError(f"Unknown filter '{key}'. Known filters: {known}") from None
