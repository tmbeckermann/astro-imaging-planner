"""Compute reference plans with the Python engine for validate.mjs to check.

Covers a deliberate spread: hemispheres, a polar site where astronomical
darkness never arrives, new/full moon, OSC/mono/stock cameras, and rigs from a
135 mm lens to an 8-inch SCT — the combinations where a ported model is most
likely to drift from the original.
"""

import json
import pathlib

from astroplanner.catalog import load_targets
from astroplanner.ephemeris import build_night
from astroplanner.exposure import optimal_sub_exposure
from astroplanner.scoring import rank_targets
from astroplanner.sensors import get_camera
from astroplanner.telescopes import get_telescope

HERE = pathlib.Path(__file__).parent

CASES = [
    # label, date, lat, lon, bortle, camera, scope, corrector
    ("stl-new-moon-osc",   "2026-08-11",  38.63,  -90.20, 6, "asi533mc",  "gt71",       "0.8x reducer"),
    ("stl-full-moon-osc",  "2026-08-27",  38.63,  -90.20, 6, "asi533mc",  "gt71",       "0.8x reducer"),
    ("dark-site-mono",     "2026-08-27",  41.66,  -77.82, 2, "asi2600mm", "edgehd8",    "0.7x reducer"),
    ("city-stock-dslr",    "2026-01-15",  40.71,  -74.01, 9, "dslr",      "samyang135", None),
    ("modded-dslr-rasa",   "2026-11-03",  35.08, -106.65, 4, "dslr-mod",  "rasa8",      None),
    ("southern-hemisphere", "2026-05-20", -33.87,  151.21, 7, "asi294mc",  "fra400",     None),
    ("high-latitude-june", "2026-06-21",  60.17,   24.94, 5, "asi183mc",  "z61",        "0.8x flattener"),
    ("equator-quarter",    "2026-03-05",   1.35,  103.82, 8, "asi585mc",  "raptor61",   None),
    # Integrated instruments: the sensor and the filter bag come with the scope,
    # so these also cover the "mode unavailable because it is not fitted" path.
    ("smart-seestar",      "2026-08-11",  36.16,  -86.78, 8, None,        "seestar50",  None),
    ("smart-dwarf3",       "2026-09-15",  36.16,  -86.78, 5, None,        "dwarf3",     None),
    ("smart-equinox2",     "2026-10-20",  41.66,  -77.82, 2, None,        "equinox2",   None),
    ("smart-dwarf-mini",   "2026-08-11",  41.66,  -77.82, 2, None,        "dwarf-mini", None),
]


def run(case) -> dict:
    label, date, lat, lon, bortle, cam_key, scope_key, corrector = case
    scope = get_telescope(scope_key)
    cam = get_camera(cam_key or scope.fixed_camera)
    fl, aperture = scope.train(corrector)
    ctx = build_night(date, lat, lon)
    ranked = rank_targets(
        ctx, cam, fl, aperture, bortle, targets=load_targets(),
        available_filters=list(scope.builtin_filters) if scope.builtin_filters else None,
        max_sub_s=scope.max_sub_s or 1200.0,
    )
    return {
        "label": label, "date": date, "lat": lat, "lon": lon, "bortle": bortle,
        "camera": cam.key, "scope": scope_key, "corrector": corrector,
        "allowed_filters": list(scope.builtin_filters) if scope.builtin_filters else None,
        "max_sub_s": scope.max_sub_s,
        "focal_length_mm": fl, "aperture_mm": aperture,
        "night": {
            "darkness_kind": ctx.darkness_kind,
            "dark_hours": ctx.dark_hours,
            "dark_start": ctx.dark_start.strftime("%H:%M") if ctx.dark_start else None,
            "dark_end": ctx.dark_end.strftime("%H:%M") if ctx.dark_end else None,
            "illumination": ctx.moon_illumination,
            "phase_angle": ctx.moon_phase_angle_deg,
            "moon_alt": [round(float(a), 4) for a in ctx.moon_alt_deg],
            "moon_up_hours": float((ctx.dark & (ctx.moon_alt_deg > 0)).sum()) * ctx.step_hours,
        },
        "targets": [
            {
                "id": r.target.id,
                "score": r.score,
                "usable_hours": r.usable_hours,
                "max_alt": r.max_alt_deg,
                "mean_moon_sep": r.mean_moon_sep_deg,
                "moon_brightening": r.moon_brightening_mag,
                "sky_quality": r.sky_quality,
                "window": list(r.best_window),
                "mode": r.mode_advice.recommended,
                "mode_filter": r.mode_advice.best.filter_key,
                "sub_s": r.mode_advice.best.recommended_sub_s,
                "sub_exact_s": optimal_sub_exposure(
                    cam.read_noise_e, r.mode_advice.best.sky_e_per_s).optimal_s,
                "sub_capped": r.mode_advice.best.sub_capped,
                "mode_sky_rate": r.mode_advice.best.sky_e_per_s,
                "mode_quality": {k: v.sky_quality for k, v in r.mode_advice.scores.items()},
                "mode_available": {k: v.available for k, v in r.mode_advice.scores.items()},
                "suggested_filter": r.suggested_filter.key,
            }
            for r in ranked
        ],
    }


if __name__ == "__main__":
    out = [run(c) for c in CASES]
    path = HERE / "reference.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {path} — {len(out)} cases, "
          f"{sum(len(c['targets']) for c in out)} ranked targets")
