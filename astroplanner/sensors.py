"""Camera sensor database.

Read noise values are at the "typical deep-sky" gain setting for each camera
(usually the HCG-mode knee, e.g. gain 100 on IMX533/571-class ZWO cameras).
QE is the approximate peak quantum efficiency. All values are close enough for
exposure planning; override any of them from the CLI for your exact settings.
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

    @property
    def width_mm(self) -> float:
        return self.width_px * self.pixel_um / 1000.0

    @property
    def height_mm(self) -> float:
        return self.height_px * self.pixel_um / 1000.0

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
        Camera("asi1600mm", "ZWO ASI1600MM Pro (MN34230)", 3.80, 4656, 3520, 1.7, "gain 139 (unity)", 0.60, 1.0, False),
        Camera("asi183mc", "ZWO ASI183MC Pro (IMX183)", 2.40, 5496, 3672, 1.6, "gain 111 (unity)", 0.84, 1.0, True),
        Camera("dslr", "Generic modern DSLR/mirrorless (APS-C)", 3.90, 6000, 4000, 2.5, "ISO 800-1600", 0.55, 0.5, True),
    ]
}


def get_camera(key: str) -> Camera:
    try:
        return CAMERAS[key.lower()]
    except KeyError:
        known = ", ".join(sorted(CAMERAS))
        raise KeyError(f"Unknown camera '{key}'. Known cameras: {known}") from None
