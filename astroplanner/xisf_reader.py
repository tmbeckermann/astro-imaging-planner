"""Minimal XISF (PixInsight) monolithic-file reader.

Supports uncompressed attachment-block images, which is what capture
software (and PixInsight with default settings minus compression) writes.
Compressed blocks raise a clear error rather than mis-reading.
"""

import re
import struct
import xml.etree.ElementTree as ET

import numpy as np

_SIGNATURE = b"XISF0100"
_DTYPES = {
    "UInt8": np.uint8,
    "UInt16": np.uint16,
    "UInt32": np.uint32,
    "Float32": np.float32,
    "Float64": np.float64,
}
_NS = {"xisf": "http://www.pixinsight.com/xisf"}


def read_xisf(path: str) -> tuple[np.ndarray, dict]:
    """Return (image_array, header_dict) for the first image in the file.

    The array is 2D for mono, (h, w, channels) for multi-channel.
    header_dict carries FITSKeyword properties embedded by capture apps
    (EXPTIME/EXPOSURE, GAIN, etc.) when present.
    """
    with open(path, "rb") as f:
        sig = f.read(8)
        if sig != _SIGNATURE:
            raise ValueError(f"{path}: not a monolithic XISF file")
        header_len = struct.unpack("<I", f.read(4))[0]
        f.read(4)  # reserved
        xml_bytes = f.read(header_len)
        root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))

        image = root.find("xisf:Image", _NS)
        if image is None:  # some writers omit the namespace
            image = root.find("Image")
        if image is None:
            raise ValueError(f"{path}: no Image element in XISF header")

        if image.get("compression"):
            raise ValueError(f"{path}: compressed XISF blocks are not supported yet")

        geometry = image.get("geometry", "")
        dims = [int(x) for x in geometry.split(":")]
        if len(dims) < 3:
            raise ValueError(f"{path}: bad geometry '{geometry}'")
        width, height, channels = dims[0], dims[1], dims[-1]

        fmt = image.get("sampleFormat", "UInt16")
        if fmt not in _DTYPES:
            raise ValueError(f"{path}: unsupported sampleFormat '{fmt}'")
        dtype = _DTYPES[fmt]

        location = image.get("location", "")
        m = re.match(r"attachment:(\d+):(\d+)", location)
        if not m:
            raise ValueError(f"{path}: unsupported data location '{location}'")
        offset, size = int(m.group(1)), int(m.group(2))

        f.seek(offset)
        raw = f.read(size)
        data = np.frombuffer(raw, dtype=dtype)
        if channels > 1:
            data = data.reshape(channels, height, width).transpose(1, 2, 0)
        else:
            data = data.reshape(height, width)

    header: dict = {}
    for kw in image.findall("xisf:FITSKeyword", _NS) + image.findall("FITSKeyword"):
        name = kw.get("name", "").strip()
        value = kw.get("value", "").strip().strip("'\" ")
        if name:
            header[name] = value
    return data, header
