"""Camera sensor database.

Read noise values are at the "typical deep-sky" gain setting for each camera
(usually the HCG-mode knee, e.g. gain 100 on IMX533/571-class ZWO cameras).
QE is the approximate peak quantum efficiency. All values are close enough for
exposure planning; override any of them from the CLI for your exact settings.

Two fields exist for the filter question rather than the exposure question:

`ha_transmission` is how much of the 656 nm Ha line the camera's own stack
passes before any filter is fitted. Dedicated astro cameras ship with a plain
AR window, so ~1.0. A stock consumer camera's IR-cut filter starts rolling off
right where Ha lives and passes only ~20% of it — which is why emission
nebulae look so thin on an unmodified DSLR, and why a duo-band bolted onto one
is mostly an OIII filter.

`builtin_ir_cut` says whether that filter is glued in front of the sensor. If
it is, "full spectrum" is not a mode you can select — you would have to modify
the camera first.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    key: str
    name: str
    pixel_um: float          # pixel pitch in microns
    width_px: int
    height_px: int
    read_noise_e: float      # electrons RMS at the typical imaging gain
    gain_setting: str        # human-readable note on which gain that is
    qe: float                # peak quantum efficiency, 0..1
    gain_e_per_adu: float    # e-/ADU at that gain setting (approximate)
    color: bool
    ha_transmission: float = 1.0   # fraction of Ha the camera stack passes
    builtin_ir_cut: bool = False   # True = IR-cut glued in, cannot go full spectrum

    @property
    def width_mm(self) -> float:
        return self.width_px * self.pixel_um / 1000.0

    @property
    def height_mm(self) -> float:
        return self.height_px * self.pixel_um / 1000.0

    @property
    def mono(self) -> bool:
        return not self.color

    def pixel_scale(self, focal_length_mm: float) -> float:
        """Image scale in arcsec/pixel at a given focal length."""
        return 206.265 * self.pixel_um / focal_length_mm

    def fov_arcmin(self, focal_length_mm: float) -> tuple[float, float]:
        """Field of view (width, height) in arcminutes."""
        return (
            3437.75 * self.width_mm / focal_length_mm,
            3437.75 * self.height_mm / focal_length_mm,
        )


CAMERAS: dict[str, Camera] = {
    c.key: c
    for c in [
        Camera("asi533mc", "ZWO ASI533MC Pro (IMX533)", 3.76, 3008, 3008, 1.0, "gain 100 (HCG)", 0.80, 0.25, True),
        Camera("asi533mm", "ZWO ASI533MM Pro (IMX533M)", 3.76, 3008, 3008, 1.0, "gain 100 (HCG)", 0.85, 0.25, False),
        Camera("asi2600mc", "ZWO ASI2600MC Pro (IMX571)", 3.76, 6248, 4176, 1.0, "gain 100 (HCG)", 0.80, 0.25, True),
        Camera("asi2600mm", "ZWO ASI2600MM Pro (IMX571M)", 3.76, 6248, 4176, 1.0, "gain 100 (HCG)", 0.85, 0.25, False),
        Camera("asi6200mm", "ZWO ASI6200MM Pro (IMX455)", 3.76, 9576, 6388, 1.2, "gain 100 (HCG)", 0.80, 0.25, False),
        Camera("asi294mc", "ZWO ASI294MC Pro (IMX294)", 4.63, 4144, 2822, 1.2, "gain 120 (HCG)", 0.75, 0.23, True),
        Camera("asi585mc", "ZWO ASI585MC (IMX585)", 2.90, 3840, 2160, 0.9, "gain 252 (HCG)", 0.91, 0.13, True),
        Camera("asi1600mm", "ZWO ASI1600MM Pro (MN34230)", 3.80, 4656, 3520, 1.7, "gain 139 (unity)", 0.60, 1.0, False),
        Camera("asi183mc", "ZWO ASI183MC Pro (IMX183)", 2.40, 5496, 3672, 1.6, "gain 111 (unity)", 0.84, 1.0, True),
        # Sensors inside integrated smart telescopes. You do not choose these —
        # the instrument comes with them — so they are selected for you when you
        # pick the scope. Pixel counts are the *usable* field the manufacturer
        # quotes, which on some instruments is smaller than the raw sensor
        # because the optics do not illuminate the whole chip.
        Camera("imx462", "Seestar S50 sensor (IMX462)", 2.90, 1920, 1080, 0.9, "built-in gain", 0.80, 0.5, True),
        # Pixel counts here are the *delivered image*, not the sensor's total
        # array: an IMX415 is 3864 x 2192 of silicon but writes a 3840 x 2160
        # picture, and it is the picture you frame with. Both makers' published
        # 35 mm-equivalent focal lengths confirm it — 675/100 for the DWARF II
        # and 737/150 for the DWARF 3 imply exactly 1.45 um and 2.00 um pixels
        # across 3840 x 2160.
        Camera("imx415", "DWARF II tele sensor (IMX415)", 1.45, 3840, 2160, 1.6, "built-in gain", 0.78, 0.5, True),
        Camera("imx678", "DWARF 3 tele sensor (IMX678)", 2.00, 3840, 2160, 1.0, "built-in gain", 0.85, 0.5, True),
        # The DWARF 3's wide lens shares that IMX678 but delivers 1920 x 1080.
        # Its published 45 mm equivalent over 6.7 mm pins the effective pixel at
        # 2.92 um, so the readout is resampled rather than a straight crop.
        Camera("imx678-wide", "DWARF 3 wide sensor (IMX678, 1080p)", 2.92, 1920, 1080, 1.0, "built-in gain", 0.85, 0.5, True),
        Camera("imx347", "Unistellar eQuinox 2 sensor (IMX347)", 2.40, 2454, 1854, 2.0, "built-in gain", 0.75, 0.5, True),
        Camera("imx662", "DWARF mini sensor (IMX662)", 2.90, 1920, 1080, 1.0, "built-in gain", 0.85, 0.5, True),
        Camera("os02k10", "DWARF mini wide sensor (OS02K10)", 2.90, 1920, 1080, 2.5, "built-in gain", 0.65, 0.5, True),
        Camera("dslr", "Stock DSLR/mirrorless (APS-C)", 3.90, 6000, 4000, 2.5, "ISO 800-1600", 0.55, 0.5, True,
               ha_transmission=0.20, builtin_ir_cut=True),
        Camera("dslr-mod", "Astro-modified DSLR/mirrorless (APS-C)", 3.90, 6000, 4000, 2.5, "ISO 800-1600", 0.55, 0.5, True,
               ha_transmission=0.97),
    ]
}


def get_camera(key: str) -> Camera:
    try:
        return CAMERAS[key.lower()]
    except KeyError:
        known = ", ".join(sorted(CAMERAS))
        raise KeyError(f"Unknown camera '{key}'. Known cameras: {known}") from None
