"""Filter database and the three practical imaging modes.

sky_bandwidth_factor expresses how much broadband sky glow the filter passes,
relative to the Johnson V band (~88 nm) that the SQM sky-brightness scale is
defined against. A UV/IR-cut ("visible") train passes roughly 3.4x the V-band
flux; a 7 nm narrowband passes ~0.08x. This is a flat-spectrum approximation —
real skyglow is not flat (LEDs, airglow lines), but it is plenty accurate for
choosing a sub length.

Removing the UV/IR cut entirely ("full spectrum") opens the sensor's whole
350-1000 nm silicon response. That is another ~1.6x of sky on top of the
visible band, because the near-IR is where the OH airglow bands live, and it
buys roughly 1.3x more continuum signal from the target. Those two nearly
cancel in SNR — which is the point worth knowing before buying a filter, and
why the mode recommendation below does not chase the last 2%.

moon_susceptibility is a rough "how much does the moon hurt" label, kept for
display only. The planner no longer uses it: scattered moonlight is solar
continuum, so sky_bandwidth_factor already describes how much of it a filter
rejects, and the Krisciunas & Schaefer model in moon.py supplies the rest.
"""

from dataclasses import dataclass

# Sky bandwidth factor of a UV/IR-cut ("visible") imaging train.
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
    needs_ir_cut_removed: bool = False   # only usable on a modified/astro camera
    colour_true: bool = True     # renders approximately correct star colour
    note: str = ""

    def signal_factor(self, line_emitter: bool, camera=None) -> float:
        """Fraction of the target's own flux this filter delivers.

        Two things a bandwidth-only model misses:

        1. A narrowband filter cuts continuum skyglow 40x while passing nearly
           all of an emission nebula's line flux. For a galaxy it cuts the
           target just as hard as the sky, which is why narrowband buys
           nothing on continuum objects.
        2. The camera's own stack has a say. An unmodified DSLR blocks ~80% of
           Ha before any filter is fitted, so on an emission nebula it is
           throwing away most of the signal whatever is screwed onto the
           front — including a duo-band, which is then mostly an OIII filter.
           `camera.ha_transmission` carries that, and it applies to line flux
           in *every* mode, not just the narrowband ones.
        """
        ha = 1.0 if camera is None else getattr(camera, "ha_transmission", 1.0)
        if not self.line_filter:
            base = self.continuum_transmission
            return base * ha if line_emitter else base
        if line_emitter:
            return self.line_transmission * ha
        return self.sky_bandwidth_factor / NO_FILTER_SKY_FACTOR


FILTERS: dict[str, Filter] = {
    f.key: f
    for f in [
        Filter("full", "Full spectrum (no UV/IR cut)", 5.5, 1.00, False,
               continuum_transmission=1.30, needs_ir_cut_removed=True,
               colour_true=False,
               note="all the photons silicon can see; bloated stars, no true colour"),
        Filter("none", "Visible (UV/IR cut)", 3.4, 1.00, False, continuum_transmission=1.00,
               note="the colour-correct broadband baseline"),
        # The DWARFs' "Astro" position passes UV and IR — it is the *open*
        # filter, not a cut one. Optically that makes it full spectrum, which
        # matters most on the DWARF mini: that instrument has no UV/IR-cut
        # position at all, so shooting it broadband means shooting full
        # spectrum, with the star bloat and colour cast that implies.
        Filter("astro", "Astro (UV + visible + IR)", 5.5, 1.00, False,
               continuum_transmission=1.30, needs_ir_cut_removed=True, colour_true=False,
               note="the open position on a DWARF; passes UV and IR, so it is full spectrum"),
        Filter("cls", "CLS / broadband light-pollution", 1.7, 0.65, False,
               continuum_transmission=0.85,
               note="notches the worst municipal lines; skews colour balance"),
        Filter("duoband", "Duo-band (Ha + OIII, ~2x7 nm)", 0.16, 0.25, True, line_transmission=0.90,
               note="the one-shot-colour nebula filter"),
        Filter("duoband-wide", "Wide duo-band (Ha + OIII, ~2x20 nm)", 0.45, 0.45, True,
               line_transmission=0.92,
               note="typical of the dual-band built into a smart telescope; check yours"),
        Filter("nb7", "Narrowband 7 nm (Ha or OIII)", 0.08, 0.15, True, line_transmission=0.90,
               note="mono, one line at a time"),
        Filter("nb3", "Narrowband 3 nm (Ha or OIII)", 0.034, 0.08, True, line_transmission=0.85,
               note="mono, deepest moonlight rejection"),
    ]
}

# The three modes the recommendation speaks in. `line` resolves to a duo-band
# on a one-shot-colour camera and to a narrowband on mono, because that is what
# each is actually used with — same physics, different hardware convention.
MODE_KEYS = ("full", "visible", "line")
MODE_LABELS = {
    "full": "Full spectrum",
    "visible": "Visible (UV/IR cut)",
    "line": "Duo-band",
}


# Which line filter each kind of camera should reach for first. A one-shot
# colour sensor wants both lines at once, since only its red pixels see Ha and
# only its green ones see OIII — shooting them one at a time wastes three
# quarters of the sensor. Mono has no such constraint and takes the narrowest
# filter on the shelf.
LINE_PREFERENCE = {
    "osc": ("duoband", "duoband-wide", "nb7", "nb3"),
    "mono": ("nb3", "nb7", "duoband", "duoband-wide"),
}

# What "visible" resolves to, in order of preference. Only genuine UV/IR-cut
# trains belong here: a DWARF's Astro position passes UV and IR, so it is a
# full-spectrum option, not a visible one, and an instrument that has only
# Astro genuinely cannot shoot a colour-correct broadband frame.
BROADBAND_PREFERENCE = ("none", "cls")

# ...and what "full spectrum" resolves to. Same optics either way; the name
# follows whichever the instrument actually offers.
FULL_PREFERENCE = ("full", "astro")


def mode_filter(mode: str, camera=None, allowed_keys: set[str] | None = None) -> Filter:
    """The concrete filter a mode means for this camera and filter bag."""
    if mode == "full":
        if allowed_keys is not None:
            owned = [k for k in FULL_PREFERENCE if k in allowed_keys]
            if owned:
                return FILTERS[owned[0]]
        return FILTERS["full"]
    if mode == "visible":
        if allowed_keys is not None:
            owned = [k for k in BROADBAND_PREFERENCE if k in allowed_keys]
            if owned:
                return FILTERS[owned[0]]
        return FILTERS["none"]
    if mode == "line":
        mono = bool(camera is not None and not getattr(camera, "color", True))
        order = LINE_PREFERENCE["mono" if mono else "osc"]
        if allowed_keys is not None:
            owned = [k for k in order if k in allowed_keys]
            if owned:
                return FILTERS[owned[0]]
        return FILTERS[order[0]]
    raise KeyError(f"Unknown imaging mode '{mode}'. Known modes: {', '.join(MODE_KEYS)}")


SHORT_BROADBAND_LABELS = {
    "none": "Visible (UV/IR cut)",
    "cls": "CLS light-pollution",
}

# Name the position the owner selects in their app.
SHORT_FULL_LABELS = {
    "full": "Full spectrum",
    "astro": "Astro (UV+vis+IR)",
}

SHORT_LINE_LABELS = {
    "duoband": "Duo-band",
    "duoband-wide": "Duo-band (wide)",
    "nb7": "Narrowband 7 nm",
    "nb3": "Narrowband 3 nm",
}


def mode_label(mode: str, camera=None, filt: "Filter | None" = None) -> str:
    """What to call this mode, given the filter it actually resolved to.

    Names follow the instrument, not the model: a DWARF mini owner sets "Astro"
    in the app, and a plan that says "Visible" is telling them to select
    something their telescope does not have.
    """
    if mode == "line":
        if filt is not None:
            return SHORT_LINE_LABELS.get(filt.key, filt.name)
        if camera is not None and not getattr(camera, "color", True):
            return "Narrowband Ha/OIII"
    elif mode == "visible" and filt is not None:
        return SHORT_BROADBAND_LABELS.get(filt.key, filt.name)
    elif mode == "full" and filt is not None:
        return SHORT_FULL_LABELS.get(filt.key, filt.name)
    return MODE_LABELS[mode]


def mode_available(mode: str, camera=None) -> bool:
    """Full spectrum needs a camera with no built-in IR-cut filter."""
    if mode != "full":
        return True
    return camera is None or not getattr(camera, "builtin_ir_cut", False)


def get_filter(key: str) -> Filter:
    try:
        return FILTERS[key.lower()]
    except KeyError:
        known = ", ".join(sorted(FILTERS))
        raise KeyError(f"Unknown filter '{key}'. Known filters: {known}") from None
