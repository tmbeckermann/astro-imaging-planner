"""Telescope database.

Only two numbers actually drive the planner — aperture (how many photons the
sky delivers per second) and focal length (how big a patch of sky each pixel
sees, hence how those photons are spread). Everything else here is labelling.

Specs are the manufacturers' nominal figures. Reducers and correctors are
listed per scope because they change the focal length, and a 0.7x reducer
moves the sub length as surely as a different camera does: it doubles the sky
flux landing on each pixel, so the sky-limited point arrives twice as soon.
Override anything with --fl / --aperture if your train differs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Telescope:
    key: str
    name: str
    aperture_mm: float
    focal_length_mm: float
    kind: str                       # refractor / newtonian / sct / rc / rasa / lens
    # (label, focal-length multiplier). The first entry is the native train.
    correctors: tuple[tuple[str, float], ...] = (("native", 1.0),)

    @property
    def f_ratio(self) -> float:
        return self.focal_length_mm / self.aperture_mm

    def train(self, corrector: str | None = None) -> tuple[float, float]:
        """(focal_length_mm, aperture_mm) with a corrector fitted."""
        if corrector is None:
            return self.focal_length_mm, self.aperture_mm
        for label, factor in self.correctors:
            if label.lower() == corrector.lower():
                return self.focal_length_mm * factor, self.aperture_mm
        known = ", ".join(label for label, _ in self.correctors)
        raise KeyError(
            f"'{corrector}' is not a corrector option for {self.name}. Options: {known}"
        )


TELESCOPES: dict[str, Telescope] = {
    t.key: t
    for t in [
        Telescope("seestar50", "ZWO Seestar S50", 50, 250, "refractor"),
        Telescope("redcat51", "William Optics RedCat 51", 51, 250, "refractor"),
        Telescope("raptor61", "Radian Raptor 61", 61, 275, "refractor"),
        Telescope("z61", "William Optics Zenithstar 61", 61, 360, "refractor",
                  (("native", 1.0), ("0.8x flattener", 0.8))),
        Telescope("evostar72", "Sky-Watcher Evostar 72ED", 72, 420, "refractor",
                  (("native", 1.0), ("0.85x reducer", 0.85))),
        Telescope("gt71", "William Optics GT71", 71, 420, "refractor",
                  (("native", 1.0), ("0.8x reducer", 0.8))),
        Telescope("fra400", "Askar FRA400", 72, 400, "refractor",
                  (("native", 1.0), ("0.7x reducer", 0.7))),
        Telescope("fra600", "Askar FRA600", 108, 600, "refractor",
                  (("native", 1.0), ("0.7x reducer", 0.7))),
        Telescope("esprit100", "Sky-Watcher Esprit 100ED", 100, 550, "refractor",
                  (("native", 1.0), ("0.77x reducer", 0.77))),
        Telescope("fsq106", "Takahashi FSQ-106EDX4", 106, 530, "refractor",
                  (("native", 1.0), ("0.73x reducer", 0.73))),
        Telescope("samyang135", "Samyang/Rokinon 135 mm f/2 lens", 67.5, 135, "lens"),
        Telescope("nt130pds", "Sky-Watcher 130PDS Newtonian", 130, 650, "newtonian",
                  (("native", 1.0), ("coma corrector 0.95x", 0.95))),
        Telescope("nt150", '6" f/5 Newtonian', 150, 750, "newtonian",
                  (("native", 1.0), ("coma corrector 0.95x", 0.95))),
        Telescope("quattro8", 'Sky-Watcher Quattro 8" f/4', 200, 800, "newtonian",
                  (("native", 1.0), ("coma corrector 0.95x", 0.95))),
        Telescope("nt200", '8" f/5 Newtonian', 200, 1000, "newtonian",
                  (("native", 1.0), ("coma corrector 0.95x", 0.95))),
        Telescope("rasa8", 'Celestron RASA 8"', 203, 400, "rasa"),
        Telescope("edgehd8", 'Celestron EdgeHD 8"', 203, 2032, "sct",
                  (("native", 1.0), ("0.7x reducer", 0.7))),
        Telescope("c8", 'Celestron C8 (SCT)', 203, 2032, "sct",
                  (("native", 1.0), ("0.63x reducer", 0.63))),
        Telescope("nexstar6", "Celestron NexStar 6SE (SCT)", 150, 1500, "sct",
                  (("native", 1.0), ("0.63x reducer", 0.63))),
        Telescope("rc8", 'GSO/TS 8" Ritchey-Chretien', 203, 1624, "rc",
                  (("native", 1.0), ("0.75x reducer", 0.75))),
    ]
}


def get_telescope(key: str) -> Telescope:
    try:
        return TELESCOPES[key.lower()]
    except KeyError:
        known = ", ".join(sorted(TELESCOPES))
        raise KeyError(f"Unknown telescope '{key}'. Known telescopes: {known}") from None
