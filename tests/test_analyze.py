import struct

import numpy as np
import pytest
from astropy.io import fits

from astroplanner.analyze import analyze_frame
from astroplanner.xisf_reader import read_xisf


@pytest.fixture
def synthetic_frame():
    rng = np.random.default_rng(42)
    img = rng.normal(500, 10, (200, 300))          # sky background 500 ADU
    img[95:105, 145:155] += 5000                   # a "star"
    return np.clip(img, 0, 65535).astype(np.uint16)


def _write_fits(path, img, exptime=120.0, egain=0.25):
    hdu = fits.PrimaryHDU(img)
    hdu.header["EXPTIME"] = exptime
    hdu.header["EGAIN"] = egain
    hdu.writeto(path)


def test_analyze_fits(tmp_path, synthetic_frame):
    path = tmp_path / "light.fits"
    _write_fits(path, synthetic_frame)
    st = analyze_frame(str(path))
    assert st.background_adu == pytest.approx(500, abs=3)
    assert st.noise_adu == pytest.approx(10, rel=0.2)
    assert st.snr > 50
    assert st.exptime_s == 120.0
    # sky rate = 500 ADU * 0.25 e-/ADU / 120 s
    assert st.sky_e_per_s == pytest.approx(500 * 0.25 / 120, rel=0.02)
    assert st.saturated_frac < 0.001


def test_analyze_offset_subtraction(tmp_path, synthetic_frame):
    path = tmp_path / "light.fits"
    _write_fits(path, synthetic_frame)
    st = analyze_frame(str(path), offset_adu=100.0)
    assert st.sky_e_per_s == pytest.approx(400 * 0.25 / 120, rel=0.02)


def _write_xisf(path, img):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xisf xmlns="http://www.pixinsight.com/xisf" version="1.0">'
        f'<Image geometry="{img.shape[1]}:{img.shape[0]}:1" sampleFormat="UInt16" '
        'colorSpace="Gray" location="attachment:4096:{size}">'
        '<FITSKeyword name="EXPTIME" value="120." comment=""/>'
        '<FITSKeyword name="EGAIN" value="0.25" comment=""/>'
        "</Image></xisf>"
    ).replace("{size}", str(img.nbytes))
    xml_b = xml.encode()
    with open(path, "wb") as f:
        f.write(b"XISF0100")
        f.write(struct.pack("<I", len(xml_b)))
        f.write(b"\x00" * 4)
        f.write(xml_b)
        f.write(b"\x00" * (4096 - 16 - len(xml_b)))
        f.write(img.tobytes())


def test_xisf_roundtrip(tmp_path, synthetic_frame):
    path = tmp_path / "light.xisf"
    _write_xisf(path, synthetic_frame)
    data, header = read_xisf(str(path))
    assert data.shape == synthetic_frame.shape
    assert np.array_equal(data, synthetic_frame)
    assert header["EXPTIME"] == "120."


def test_analyze_xisf(tmp_path, synthetic_frame):
    path = tmp_path / "light.xisf"
    _write_xisf(path, synthetic_frame)
    st = analyze_frame(str(path))
    assert st.background_adu == pytest.approx(500, abs=3)
    assert st.sky_e_per_s == pytest.approx(500 * 0.25 / 120, rel=0.02)
