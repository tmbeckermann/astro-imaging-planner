"""Render the built page in Chromium and check it holds up.

Screenshots both themes and a few rig combinations, and fails on any console
error, page error, or horizontal overflow — the three things that make a
self-contained page look fine in source and broken on screen.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
PAGE = "file://" + str((HERE / "dist" / "tonight.html").resolve())
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def shots(outdir: pathlib.Path):
    outdir.mkdir(parents=True, exist_ok=True)
    problems = []

    # Order matters: the camera control is disabled while an integrated
    # instrument is selected, so the scope has to change first.
    def act_mono(pg):
        pg.select_option("#scopeInput", "edgehd8")
        pg.select_option("#correctorInput", "0.7x reducer")
        pg.select_option("#cameraInput", "asi2600mm")

    def act_stock(pg):
        pg.select_option("#scopeInput", "samyang135")
        pg.select_option("#cameraInput", "dslr")

    def act_search(pg):
        pg.fill("#placeInput", "cherry")

    def act_utc_metric(pg):
        pg.select_option("#tzInput", "UTC")
        pg.select_option("#unitsInput", "metric")

    def act_pacific(pg):
        pg.fill("#placeInput", "los angeles")
        pg.keyboard.press("Enter")
        pg.select_option("#tzInput", "America/Los_Angeles")

    def act_seestar(pg):
        pg.select_option("#scopeInput", "seestar50")

    def act_equinox(pg):
        pg.select_option("#scopeInput", "equinox2")

    def act_mini(pg):
        pg.select_option("#scopeInput", "dwarf-mini")
        pg.fill("#placeInput", "cherry springs")
        pg.keyboard.press("Enter")

    def act_wide(pg):
        pg.select_option("#scopeInput", "dwarf-mini-wide")
        pg.fill("#placeInput", "cherry springs")
        pg.keyboard.press("Enter")

    def act_sqm(pg):
        pg.fill("#sqmInput", "19.35")

    def act_paste_coords(pg):
        pg.fill("#placeInput", "36.0289, -86.6656")
        pg.keyboard.press("Enter")

    def act_darksite(pg):
        pg.fill("#placeInput", "big bend")
        pg.keyboard.press("Enter")

    cases = [
        ("dark", 1280, 1500, "page-dark", None),
        ("light", 1280, 1500, "page-light", None),
        ("dark", 1280, 1500, "page-mono-sct", act_mono),
        ("dark", 1280, 1500, "page-stock-dslr", act_stock),
        ("dark", 1280, 900, "page-search", act_search),
        ("dark", 1280, 1500, "page-dark-site", act_darksite),
        ("dark", 1280, 1500, "page-seestar", act_seestar),
        ("dark", 1280, 1500, "page-equinox2", act_equinox),
        ("dark", 1280, 1200, "page-dwarf-mini", act_mini),
        ("dark", 1280, 1200, "page-dwarf-wide", act_wide),
        ("dark", 1280, 900, "page-sqm", act_sqm),
        ("dark", 1280, 900, "page-paste-coords", act_paste_coords),
        ("dark", 1280, 900, "page-utc-metric", act_utc_metric),
        ("dark", 1280, 900, "page-pacific", act_pacific),
        ("dark", 420, 2000, "page-mobile", None),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        for scheme, w, h, name, action in cases:
            page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
            msgs = []
            page.on("console", lambda m: msgs.append((m.type, m.text)))
            page.on("pageerror", lambda e: msgs.append(("pageerror", str(e))))
            page.goto(PAGE)
            page.wait_for_timeout(600)
            if action:
                action(page)
                page.wait_for_timeout(500)
            page.screenshot(path=str(outdir / f"{name}.png"), full_page=False)
            bad = [m for m in msgs if m[0] in ("error", "pageerror")]
            if bad:
                problems.append(f"{name}: {bad}")
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            if overflow > 1:
                problems.append(f"{name}: page scrolls sideways by {overflow}px")
            page.close()
        browser.close()

    return problems


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "dist" / "shots"
    issues = shots(out)
    if issues:
        print("\n".join(issues))
        sys.exit(1)
    print(f"rendered clean into {out}: no console errors, no horizontal overflow")
