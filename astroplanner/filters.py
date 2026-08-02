"""Filter database.

sky_bandwidth_factor expresses how much broadband sky glow the filter passes,
relative to the Johnson V band (~88 nm) that the SQM sky-brightness scale is
defined against. A full-visible-spectrum filter passes roughly 3.4x the V-band
flux; a 7 nm narrowband passes ~0.08x. This is a flat-spectrum approximation —
real skyglow is not flat (LEDs, airglow lines), but it is plenty accurate for
choosing a sub length.

moon_resistance scales how strongly scattered moonlight degrades the target
(1.0 = fully affected, small = mostly immune). Narrowband filters reject most
of the moonlit continuum.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Filter:
    key: str
    name: str
    sky_bandwidth_factor: float
    moon_susceptibility: float   # 1.0 = broadband, lower = more moon-proof
    line_filter: bool            # passes only emission lines (Ha/OIII/SII)


FILTERS: dict[str, Filter] = {
    f.key: f
    for f in [
        Filter("none", "No filter / UV-IR cut", 3.4, 1.00, False),
        Filter("cls", "CLS / broadband light-pollution", 1.7, 0.65, False),
        Filter("duoband", "Duo-band (Ha + OIII, ~2x7 nm)", 0.16, 0.25, True),
        Filter("nb7", "Narrowband 7 nm (Ha or OIII)", 0.08, 0.15, True),
        Filter("nb3", "Narrowband 3 nm (Ha or OIII)", 0.034, 0.08, True),
    ]
}


def get_filter(key: str) -> Filter:
    try:
        return FILTERS[key.lower()]
    except KeyError:
        known = ", ".join(sorted(FILTERS))
        raise KeyError(f"Unknown filter '{key}'. Known filters: {known}") from None
