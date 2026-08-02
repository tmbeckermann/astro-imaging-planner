"""Bundled deep-sky target catalog (popular imaging targets).

Types: emission, reflection, galaxy, planetary, cluster, snr.
Emission nebulae, supernova remnants, and planetaries emit mostly in
narrow lines (Ha/OIII/SII), so line filters (duoband/narrowband) work on
them; galaxies, reflection nebulae, and clusters are broadband objects.
"""

import csv
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
