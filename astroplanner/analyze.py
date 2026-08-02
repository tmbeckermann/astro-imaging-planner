"""Sub-frame quality analysis for FITS and XISF light frames.

Reports background level, robust noise (via MAD), a simple SNR figure for
the bright structure in the frame, and — when exposure time and camera
gain are known — the measured sky flux in e-/pixel/s. That measured rate
can be fed straight back into the exposure calculator, replacing the
Bortle estimate with reality at your site.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits

from .xisf_reader import read_xisf

MAD_TO_SIGMA = 1.4826


@dataclass
class FrameStats:
    path: str
    shape: tuple
    background_adu: float
    noise_adu: float
    signal_adu: float       # 99.9th percentile above background
    snr: float
    exptime_s: float | None
    sky_e_per_s: float | None   # requires exptime + gain (+ optional offset)
    saturated_frac: float


def load_frame(path: str) -> tuple[np.ndarray, dict]:
    p = Path(path)
    if p.suffix.lower() == ".xisf":
        return read_xisf(str(p))
    with fits.open(str(p)) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        return np.asarray(hdu.data), dict(hdu.header)


def _to_float(header: dict, *keys: str) -> float | None:
    for k in keys:
        if k in header:
            try:
                return float(header[k])
            except (TypeError, ValueError):
                continue
    return None


def analyze_frame(
    path: str,
    gain_e_per_adu: float | None = None,
    offset_adu: float | None = None,
    exptime_s: float | None = None,
) -> FrameStats:
    data, header = load_frame(path)
    img = data.astype(np.float64)
    if img.ndim == 3:  # color: analyze luminance-ish mean of channels
        img = img.mean(axis=2)

    background = float(np.median(img))
    mad = float(np.median(np.abs(img - background)))
    noise = MAD_TO_SIGMA * mad
    signal = float(np.percentile(img, 99.9)) - background
    snr = signal / noise if noise > 0 else float("inf")

    if np.issubdtype(data.dtype, np.integer):
        sat_level = float(np.iinfo(data.dtype).max)
    else:
        sat_level = 1.0 if float(img.max()) <= 1.0 else float(img.max())
    saturated_frac = float(np.mean(img >= 0.98 * sat_level))

    exptime = exptime_s if exptime_s is not None else _to_float(header, "EXPTIME", "EXPOSURE")
    gain = gain_e_per_adu if gain_e_per_adu is not None else _to_float(header, "EGAIN")
    offset = offset_adu if offset_adu is not None else _to_float(header, "PEDESTAL", "BLKLEVEL", "OFFSET")

    sky_rate = None
    if exptime and gain and exptime > 0:
        sky_adu = background - (offset or 0.0)
        if sky_adu > 0:
            sky_rate = sky_adu * gain / exptime

    return FrameStats(
        path=path,
        shape=tuple(data.shape),
        background_adu=background,
        noise_adu=noise,
        signal_adu=signal,
        snr=snr,
        exptime_s=exptime,
        sky_e_per_s=sky_rate,
        saturated_frac=saturated_frac,
    )
