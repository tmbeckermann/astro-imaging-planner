"""Build the standalone Messier-catalog page.

    python web/build_messier.py [-o path/to/messier.html]

Same inlining approach as build.py: webcore.js and the exported databases get
pasted into messier_page.html so the page needs no server or build step at
view time.
"""

import argparse
import json
import pathlib
import re

from export_data import build as build_data

HERE = pathlib.Path(__file__).parent

DEFAULTS = {
    "place": "Nashville",
    "bortle": 6,
    "fallbackCamera": "asi533mc",
    "scope": "dwarf-mini",
    "corrector": "native",
    "camera": "imx662",
    "units": "imperial",
}


def build(out_path: pathlib.Path) -> pathlib.Path:
    core = (HERE / "webcore.js").read_text()
    core = re.sub(r"^export ", "", core, flags=re.MULTILINE)
    page = (HERE / "messier_page.html").read_text()
    html = (
        page.replace("__CORE_JS__", core)
        .replace("__DATA_JSON__", json.dumps(build_data(), separators=(",", ":")))
        .replace("__DEFAULTS__", json.dumps(DEFAULTS))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(HERE / "dist" / "messier.html"))
    args = ap.parse_args()
    path = build(pathlib.Path(args.out))
    print(f"wrote {path} — {path.stat().st_size / 1024:.0f} kB")
