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
    kind: str                       # refractor / newtonian / sct / rc / rasa / lens / smart
    # (label, focal-length multiplier). The first entry is the native train.
    correctors: tuple[tuple[str, float], ...] = (("native", 1.0),)
    # An integrated instrument (a "smart telescope") is not a scope you put a
    # camera on: the sensor is bonded to it and the filters are whatever the
    # maker fitted. Modelling that honestly is the difference between advice you
    # can act on and advice that assumes a filter drawer you do not have.
    fixed_camera: str | None = None
    builtin_filters: tuple[str, ...] | None = None
    # Longest sub the instrument will actually take. A sealed instrument can
    # have a ceiling below its own optimum, in which case the honest advice is
    # "you cannot get there, shoot more subs" rather than a number you cannot
    # dial in. None means no known limit, which is not the same as unlimited.
    max_sub_s: float | None = None
    # Which parts of this entry are inferred rather than published, e.g.
    # ("aperture",) or ("sensor",). Sky rates scale with aperture squared and
    # with pixel scale squared, so an inference in either is not a footnote —
    # it travels with every number the planner prints from it.
    assumed: tuple[str, ...] = ()
    spec_note: str = ""

    @property
    def aperture_assumed(self) -> bool:
        return "aperture" in self.assumed

    @property
    def integrated(self) -> bool:
        return self.fixed_camera is not None

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
        # --- integrated smart telescopes -------------------------------------
        # Aperture and focal length are the manufacturers' published figures.
        # Pixel counts are the usable field, cross-checked against each maker's
        # quoted field of view: Seestar 1.29 x 0.73 deg, DWARF II 3.0 x 1.7 deg,
        # DWARF 3 2.9 x 1.6 deg all reproduce to within a few percent. Read
        # noise and QE are nominal for the sensor, not measured units — override
        # with --read-noise / --qe if you have your own numbers.
        Telescope("seestar50", "ZWO Seestar S50", 50, 250, "smart",
                  fixed_camera="imx462", builtin_filters=("none", "duoband-wide"),
                  spec_note="built-in UV/IR cut plus a dual-band"),
        Telescope("dwarf2", "DwarfLab DWARF II (telephoto)", 24, 100, "smart",
                  fixed_camera="imx415", builtin_filters=("none", "duoband-wide"),
                  spec_note="dual-band is the optional magnetic filter; drop it with --filters none"),
        Telescope("dwarf3", "DwarfLab DWARF 3 (telephoto)", 35, 150, "smart",
                  fixed_camera="imx678", builtin_filters=("none", "duoband-wide"),
                  spec_note="switchable built-in VIS and dual-band filters"),
        Telescope("dwarf-mini", "DwarfLab DWARF mini (telephoto)", 30, 150, "smart",
                  fixed_camera="imx662", builtin_filters=("none", "cls", "duoband-wide"),
                  max_sub_s=90,
                  spec_note="LP, nebula and Ha/Hb/OIII filters; the dual-band is what is modelled"),
        # The wide-angle modules. The DWARF 3's optics are published (3.4 mm at
        # 6.7 mm, f/2.0); its sensor is not confirmed here, so the pixel scale
        # is inferred from the mini's wide module.
        #
        # The mini's own spec sheet repeats the telephoto's "30 mm aperture",
        # which cannot be the entrance pupil: 30 mm at 6.7 mm focal length is
        # f/0.22, and no lens in air can go below f/0.5. Since the mini's wide
        # lens has the same 6.7 mm focal length as the DWARF 3's, that
        # instrument's published 3.4 mm is a far better basis than a generic
        # guess — but it is still an inference, and stays flagged as one.
        # The DWARF II's wide lens: f/2.4 and "2 Megapixel" are published, the
        # focal length is not. It matters less than it looks. Sky rate per pixel
        # goes as aperture^2 x pixel-scale^2, aperture is focal length / f-ratio
        # and pixel scale is 206.265 x pixel / focal length — so the focal
        # length cancels, and the sub length follows from f/2.4 and the pixel
        # pitch alone. Only the field of view and the arcsec/pixel figure depend
        # on the 6.7 mm here, which is taken from its siblings and consistent
        # with the table's "up to 50 degrees" over 1920 pixels.
        Telescope("dwarf2-wide", "DwarfLab DWARF II (wide-angle)", 2.79, 6.7, "smart",
                  fixed_camera="os02k10", builtin_filters=("none",),
                  assumed=("focal length", "sensor"),
                  spec_note="f/2.4 published; focal length from its siblings — the sub length "
                            "does not depend on it, the field of view does"),
        Telescope("dwarf3-wide", "DwarfLab DWARF 3 (wide-angle)", 3.4, 6.7, "smart",
                  fixed_camera="os02k10", builtin_filters=("none",),
                  assumed=("sensor",),
                  spec_note="optics published; sensor taken from the mini's wide module"),
        Telescope("dwarf-mini-wide", "DwarfLab DWARF mini (wide-angle)", 3.4, 6.7, "smart",
                  fixed_camera="os02k10", builtin_filters=("none",), max_sub_s=90,
                  assumed=("aperture",),
                  spec_note="aperture taken from the DWARF 3's published wide module (f/2.0)"),
        Telescope("equinox2", "Unistellar eQuinox 2", 114, 450, "smart",
                  fixed_camera="imx347", builtin_filters=("none",),
                  spec_note="no filter slot: narrowband is not available on this instrument"),
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
