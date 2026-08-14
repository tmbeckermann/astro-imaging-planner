# Handoff — astro-imaging-planner

Everything needed to pick this project up on another machine, with or without
an AI assistant. Nothing here needs the session it was built in.

**What it is:** an astrophotography planner. Given a night, a site and a rig it
ranks deep-sky targets, says whether to shoot each one in **full spectrum**,
**visible (UV/IR cut)** or **duo-band**, and gives the sub-exposure length at
which sky noise swamps read noise. A command-line tool plus a self-contained
web page.

---

## 1. What's in the zip

```
astro-imaging-planner/
├─ HANDOFF.md              ← you are here
├─ README.md               ← the project's own docs: usage, physics, roadmap
├─ pyproject.toml
├─ astroplanner/           ← the engine (Python)
│  ├─ ephemeris.py            night grid, darkness window, target tracks (astropy)
│  ├─ moon.py                 Krisciunas & Schaefer moonlight scattering
│  ├─ sky.py                  Bortle → SQM → sky electrons/pixel/second
│  ├─ exposure.py             Glover optimal sub-exposure
│  ├─ filters.py              filter model + the three imaging modes
│  ├─ scoring.py              ranking and the mode recommendation
│  ├─ sensors.py              camera database (Hα transmission, IR-cut, read noise)
│  ├─ telescopes.py           telescope database with reducers/correctors
│  ├─ geocode.py              site search: bundled gazetteer + online geocoder
│  ├─ units.py                timezone and imperial/metric presentation
│  ├─ catalog.py, analyze.py, sessionlog.py, xisf_reader.py
│  └─ data/                   targets.csv (58 targets), places.csv (99 places)
├─ tests/                  ← 105 tests, pytest
├─ web/
│  ├─ webcore.js              the whole model ported to JavaScript
│  ├─ page.html               page template (data + core are inlined at build)
│  ├─ build.py                → web/dist/tonight.html
│  ├─ export_data.py          dumps the Python databases to web/data.json
│  ├─ dump_reference.py       computes reference plans with the Python engine
│  ├─ validate.mjs            checks the JS against those references
│  └─ shoot.py                renders the built page in Chromium, fails on errors
├─ tonight.html            ← the built page. Double-click it; nothing else needed
└─ astro-imaging-planner.bundle   ← the full git history, as a clonable bundle
```

## 2. Run it

```bash
cd astro-imaging-planner
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                           # numpy + astropy, ~1 min
pytest                                            # 105 passing

astroplanner plan --date 2026-08-11 --place nashville --camera asi533mc --scope gt71
astroplanner scopes          # what telescopes it knows
astroplanner cameras
astroplanner places "cherry springs"
```

Defaults are Central time and imperial units (`--tz`, `--units`). The plan
prints each target's recommended mode and a comparison of all three.

Rebuild the web page (needs nothing but Python):

```bash
python web/build.py          # → web/dist/tonight.html
```

Check the JavaScript port still agrees with the Python engine (needs Node 18+):

```bash
python web/export_data.py && python web/dump_reference.py && node web/validate.mjs
```

That last command is the project's spine — see §4.

## 3. Restore the git history

The zip carries a git bundle rather than a `.git` directory:

```bash
git clone astro-imaging-planner.bundle astro-imaging-planner-git
cd astro-imaging-planner-git
git log --oneline          # the whole history, oldest commit first is the prototype
git remote set-url origin https://github.com/<you>/astro.git
git push -u origin main
```

The bundle is a complete repository — clone it and you have the history, not
just the files.

## 4. Handing it to an AI assistant

### Claude Code (any machine) — the best fit

Unzip, then from inside the folder run `claude`. It reads the repo directly.
Paste this to orient it:

> This is astro-imaging-planner, an astrophotography planner. Read HANDOFF.md
> and README.md first, then astroplanner/scoring.py and web/webcore.js.
>
> Ground rules that matter here:
> - The Python package is the source of truth. web/webcore.js is a port of it,
>   and `node web/validate.mjs` checks the two agree target-by-target across
>   eight sites/dates/rigs. If you change the model in Python, re-run
>   `python web/export_data.py && python web/dump_reference.py && node
>   web/validate.mjs` and fix any drift before you call the change done.
> - Run `pytest` before and after. 105 tests currently pass.
> - The sky model assumes a flat spectrum. Several results depend on that
>   (the moon's fractional cost cancelling across filters, narrowband's
>   advantage being site-independent). Don't "fix" those — they're
>   consequences, and the docstrings explain them.
>
> Here's what I want to change: <your task>

### Claude.ai / ChatGPT in the browser — upload the zip

Both will read the files but neither reliably *runs* this: astropy is a large
dependency their sandboxes usually can't install, and there's no network to
fetch it. What does work in a browser sandbox:

- Reading and editing any of the source.
- Running `node web/validate.mjs` **if** the environment has Node — the JS core
  has zero dependencies, and `web/reference.json` is pre-computed by the Python,
  so the cross-check runs without astropy.
- Opening `tonight.html` — it needs nothing at all.

Opening prompt:

> Attached is astro-imaging-planner, a Python + JavaScript astrophotography
> planner. Start with HANDOFF.md and README.md, then astroplanner/scoring.py.
> Note that astroplanner/ needs numpy and astropy, which you probably cannot
> install — so reason about the Python, and if you want to check a numeric
> change, use web/webcore.js with Node, which has no dependencies. Tell me the
> exact commands to run on my own machine to verify anything you change.
> My task: <your task>

### The single most useful thing to tell any assistant

The model's non-obvious results are load-bearing and each is explained in a
docstring. Skim these before changing anything:

- `scoring.py::recommend_mode` — why full spectrum is a ~2% SNR gain and
  therefore *not* recommended, and why a line filter's advantage doesn't depend
  on how dark your site is.
- `filters.py` module docstring — where the near-IR sky/target asymmetry
  (1.6× sky, 1.3× signal) comes from.
- `ephemeris.py::target_track` — the moon-separation frame bug that a
  cross-check caught. It's a live trap in astropy, not a historical note.

## 5. State of things

**Working and verified:** 105 tests pass. The JS port matches the Python engine
on ranking order, recommended mode, sub length and SkyQual for all 430 ranked
targets across twelve sites, dates and rigs (including four smart telescopes); ephemeris agrees with astropy to
0.15° (moon) and 0.008° (targets). The page renders clean in Chromium, both
themes, no console errors, no horizontal overflow.

**Known limits, all deliberate:**

- The online geocoder path (`geocode.search_online`, Open-Meteo) is **untested
  against the live API** — the machine it was written on had no egress to it.
  It's covered by a test with a stubbed response, so the parsing is right, but
  the first real call is unproven. `--offline` avoids it entirely.
- Sky class for towns is a population heuristic, labelled `estimated`;
  characterised dark-sky sites are labelled `measured`; cities with a stated
  value are `typical`. None of these is a meter reading at your parking spot —
  check lightpollutionmap.info.
- Flat sky spectrum. Real skyglow is line-rich (LEDs, airglow), which is why a
  spectral sky model is the top roadmap item in README.md.
- Camera and telescope specs are manufacturers' nominal figures. Override with
  `--read-noise`, `--qe`, `--fl`, `--aperture`.
- Browser geolocation ("Use my location") needs a secure page. Opening
  `tonight.html` from disk, or inside a sandboxed iframe that was not granted
  the permission, will fail — the button says which. Pasting coordinates or a
  maps link always works.
- Smart-telescope read noise and QE are nominal for the sensor, not measured
  for your unit. The DWARF mini wide-angle's *aperture* is an assumption
  (f/2.4) flagged in the UI, because its spec sheet's figure is physically
  impossible; sky rates scale with its square. Aperture, focal length and field of view are pinned by a test
  against each maker's published figures.
- The web page is a static build from a bundled snapshot of the databases.
  Editing `astroplanner/data/*.csv` requires re-running `python web/build.py`
  for the page to see it.

**Not done:** the code was never pushed to GitHub. The session that wrote it
lost GitHub access partway through (an org-level policy denial — "an org admin
must connect the Claude GitHub App"), so the bundle in §3 is the canonical
copy of the history.
