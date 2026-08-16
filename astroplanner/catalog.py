"""Bundled deep-sky target catalog (popular imaging targets).

Types: emission, reflection, galaxy, planetary, cluster, snr.
Emission nebulae, supernova remnants, and planetaries emit mostly in
narrow lines (Ha/OIII/SII), so line filters (duoband/narrowband) work on
them; galaxies, reflection nebulae, and clusters are broadband objects.
"""

import csv
import math
from dataclasses import dataclass
from importlib import resources

LINE_EMISSION_TYPES = {"emission", "snr", "planetary"}


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    ra_deg: float
    dec_deg: float
    size_arcmin: float
    type: str
    mag: float

    @property
    def line_emitter(self) -> bool:
        return self.type in LINE_EMISSION_TYPES

    @property
    def surface_brightness_mag(self) -> float:
        """Average V-band surface brightness, mag/arcsec^2, from catalog mag + size.

        SB = m + 2.5*log10(A), spreading the integrated magnitude over the
        object's own apparent area rather than a point. The catalog stores one
        size (the published major axis), so this treats the object as a circle
        of that diameter — for an elongated target (M31 is 178' x 63') that
        overstates the area and so understates (dims) the true surface
        brightness, which is the conservative direction to be wrong in: it
        under-promises depth rather than over-promising it.

        For a line emitter this is still a V-band figure, not an Ha/OIII flux —
        catalog visual magnitudes for emission nebulae are notoriously rough,
        and V-band only partly overlaps the Ha line at 656 nm. Treat estimates
        for emission/SNR/planetary targets as an order-of-magnitude guide, not
        a number to plan a session around the way a galaxy's estimate can be.
        """
        area_arcsec2 = math.pi / 4.0 * (self.size_arcmin * 60.0) ** 2
        return self.mag + 2.5 * math.log10(area_arcsec2)


def load_targets() -> list[Target]:
    path = resources.files("astroplanner").joinpath("data/targets.csv")
    targets = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            targets.append(
                Target(
                    id=row["id"],
                    name=row["name"],
                    ra_deg=float(row["ra_deg"]),
                    dec_deg=float(row["dec_deg"]),
                    size_arcmin=float(row["size_arcmin"]),
                    type=row["type"],
                    mag=float(row["mag"]),
                )
            )
    return targets
