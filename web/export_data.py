"""Dump the planner's databases to web/data.json for the browser build.

The web page must not carry its own copy of the catalog, the camera specs or
the filter model — one edit in astroplanner/ should move both. This script is
that link; build.py runs it before inlining anything.
"""

import json
import pathlib
from dataclasses import asdict

from astroplanner.catalog import load_targets
from astroplanner.filters import FILTERS
from astroplanner.geocode import load_places
from astroplanner.sensors import CAMERAS
from astroplanner.telescopes import TELESCOPES

HERE = pathlib.Path(__file__).parent


def build() -> dict:
    return {
        "filters": {k: asdict(f) for k, f in FILTERS.items()},
        "cameras": [asdict(c) for c in CAMERAS.values()],
        "telescopes": [
            {**asdict(t), "correctors": [list(c) for c in t.correctors], "f_ratio": t.f_ratio}
            for t in TELESCOPES.values()
        ],
        "targets": [{**asdict(t), "line_emitter": t.line_emitter} for t in load_targets()],
        "places": [
            {**asdict(p), "label": p.label, "bortle_estimate": p.bortle_estimate,
             "bortle_basis": p.bortle_basis, "bortle_measured": p.bortle_is_measured}
            for p in load_places()
        ],
    }


if __name__ == "__main__":
    path = HERE / "data.json"
    path.write_text(json.dumps(build(), separators=(",", ":")))
    data = build()
    print(f"wrote {path} — {len(data['targets'])} targets, {len(data['cameras'])} cameras, "
          f"{len(data['telescopes'])} scopes, {len(data['places'])} places")
