"""Build the standalone planner page.

    python web/build.py [-o path/to/tonight.html]

Inlines the shared core and the exported databases into one self-contained
file — no network, no build step at view time. `export` keywords are stripped
because the core is concatenated into a single inline module rather than
imported.
"""

import argparse
import json
import pathlib
import re

from export_data import build as build_data

HERE = pathlib.Path(__file__).parent

DEFAULTS = {
    "place": "Saint Louis",
    "date": "2026-08-11",
    "bortle": 6,
    "scope": "gt71",
    "corrector": "0.8x reducer",
    "camera": "asi533mc",
}


def build(out_path: pathlib.Path) -> pathlib.Path:
    core = (HERE / "webcore.js").read_text()
    core = re.sub(r"^export ", "", core, flags=re.MULTILINE)
    page = (HERE / "page.html").read_text()
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
    ap.add_argument("-o", "--out", default=str(HERE / "dist" / "tonight.html"))
    args = ap.parse_args()
    path = build(pathlib.Path(args.out))
    print(f"wrote {path} — {path.stat().st_size / 1024:.0f} kB")
