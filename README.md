# astro-imaging-planner

"What am I going to image tonight — and how long should my subs be?"

A command-line astrophotography assistant:

- **Nightly planner** — ranks the best deep-sky targets for your date, site,
  and rig, using real sun/moon/target ephemerides (astropy). Scores combine
  usable dark hours above 30°, altitude quality, moonlight interference, and
  how well the target fits your field of view.
- **Optimal sub-exposure calculator** — implements Robin Glover's
  (SharpCap) sky-limited exposure model: your Bortle class (or a measured
  SQM / sky rate), the sensor's read noise and QE, your optics, and the
  filter bandwidth determine the sub length where read noise stops
  mattering.
- **Physical moonlight model** — Krisciunas & Schaefer (1991) scattering, so
  the moon's cost depends on its phase, its altitude, the target's altitude,
  and their angular separation. Feeds both the ranking and the sub length:
  under a bright moon the sky is brighter, so optimal subs get *shorter*.
- **Imaging-mode advisor** — for every target, scores the three things you can
  actually put in front of the sensor: **full spectrum** (no UV/IR cut),
  **visible** (UV/IR cut), and **duo-band** (Ha+OIII; a narrowband on mono).
  It knows which targets are line emitters, and it knows your camera — an
  unmodified DSLR passes ~20% of Ha, so a duo-band on one is mostly an OIII
  filter, and full spectrum is not a mode it can shoot at all.
- **Site and rig databases** — search observing sites and towns by name
  (`--place "cherry springs"`), paste coordinates or a maps link, and pick a
  telescope by key (`--scope gt71 --corrector "0.8x reducer"`) instead of
  typing focal lengths.
- **Smart telescopes as what they are** — a Seestar S50, DWARF II, DWARF 3,
  DWARF mini or Unistellar eQuinox 2 is not a tube you choose a camera for: the sensor is
  bonded in and the filters are whatever the maker fitted. Pick one and the
  camera follows, and the advice is limited to filters that instrument
  physically has. An eQuinox 2 has no filter slot, so it is told to shoot
  emission nebulae broadband instead of being advised to buy narrowband it
  cannot mount.
- **Times you'd actually set an alarm for** — everything is computed in UTC and
  displayed in your zone (`--tz`, default `America/Chicago`), with the
  abbreviation the date is actually in, CDT or CST. Elevations and apertures
  follow `--units` (default `imperial`).
- **FITS/XISF analyzer** — measures background, noise, SNR, and the *actual*
  sky electron rate of your light frames, which you can feed back into the
  exposure calculator to replace the Bortle estimate with reality.
- **Session logger** — SQLite log of what you shot, with what, for how long.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # optional: run the test suite
```

## Usage

Plan tonight, naming the site and the scope:

```bash
astroplanner plan --date 2026-08-02 --place "st louis" \
    --camera asi533mc --scope gt71 --corrector "0.8x reducer" --top 5
```

`--place` searches the bundled gazetteer first (towns plus dark-sky observing
sites) and falls back to the Open-Meteo geocoder for anywhere else; `--offline`
skips the network entirely. The site's sky class is filled in for you, labelled
with how much to trust it: **measured** at a characterised observing site,
**typical** for a city that size, or **estimated** from population. Check it on
lightpollutionmap.info and override with `--bortle`. Coordinates still work:
`--lat 38.6 --lon -90.2 --bortle 7 --fl 500 --aperture 80`.

Coordinates work wherever a place name does — `--place "36.1627, -86.7816"`,
`--place "36°09'46\"N 86°46'54\"W"`, or a pasted Google/Apple Maps link. That is
the practical "pick a point on a map": drop a pin in the map app you already
use, copy, paste. A bare position carries no sky class, so pass `--bortle`.

Times print in `--tz` (default Central), so a plan reads `21:23-04:23 CDT`
rather than `02:42-09:30 UTC` — the same instants, in the zone you are standing
in. `--tz UTC` if you would rather keep the log in UTC.

Every plan reports all three modes per target, so the recommendation shows its
working:

```
  Mode comparison (SkyQual, 1.00 = visible train under a moonless sky here):
      Full spectrum          1.02     5s subs
      Visible (UV/IR cut)    1.00    10s subs
   -> Duo-band               4.15   180s subs
```

Optimal sub length for a duo-band filter under that sky:

```bash
astroplanner exposure --bortle 7 --camera asi533mc --scope gt71 --filter duoband
```

Measure a real sub and close the loop:

```bash
astroplanner analyze Light_NGC7000_300s.fits
# ... measured sky 0.412 e-/px/s
astroplanner exposure --sky-rate 0.412 --camera asi533mc --fl 500 --aperture 80 --filter duoband
```

Log the session:

```bash
astroplanner log add --date 2026-08-02 --target NGC7000 --filter duoband \
    --sub 300 --subs 24 --notes "first light with the duoband"
astroplanner log list
```

Restrict to the filters you actually own, or to a kind of target:

```bash
astroplanner plan ... --filters none,cls      # no narrowband in the drawer
astroplanner plan ... --type galaxy,cluster   # galaxy night
```

Reference lists: `astroplanner cameras`, `astroplanner scopes`,
`astroplanner filters`, `astroplanner targets`, `astroplanner places <query>`.
Unknown camera or scope? Override with `--read-noise` / `--qe` /
`--fl` / `--aperture` on any command.

## The physics, briefly

Each sub-frame carries a fixed dose of read noise; sky background shot noise
grows with exposure time. Once sky noise "swamps" read noise, longer subs
stop improving the stack — they only add risk (satellites, guiding, wind).
Requiring at most an E% total-noise penalty vs. an ideal camera gives

```
t_opt = R² / ( ((1 + E/100)² − 1) · P )
```

with R = read noise (e⁻) and P = sky rate (e⁻/px/s). P is derived from the
Bortle→SQM mapping, the V-band photometric zero point, aperture area, pixel
scale, QE and the filter's bandwidth — or measured directly from your frames
with `analyze`. Narrowband filters cut P by 40×+, which is why 300–600 s
narrowband subs coexist with 30 s broadband subs in the same sky.

Moonlight adds to P through the Krisciunas & Schaefer model, so a full moon
shortens the recommended sub as well as costing SNR. Two consequences are
worth knowing, because both are easy to guess wrong:

- **The darkest sky is ~90° from the moon, not opposite it.** Rayleigh
  scattering carries a `cos²ρ` term, so backscatter brightens the anti-moon
  point again.
- **A filter does not reduce the moon's *fractional* cost.** Moonlight and
  light-pollution skyglow are both continuum, so any filter attenuates both
  equally and the ratio cancels. What narrowband buys is *absolute* SNR: it
  passes the line flux while cutting continuum sky, so an Hα sub under a full
  moon can beat an unfiltered sub under a dark sky. The `SkyQual` column
  reports that (1.00 = unfiltered under your moonless sky).

### Why full spectrum is a wash

Removing the UV/IR cut opens the sensor's full 350-1000 nm response. That is
about 1.6x more sky but only about 1.3x more target, because the near-IR is
where the OH airglow bands live and most deep-sky continuum is not especially
NIR-bright. Net, roughly +2% SNR — real, but not worth losing true star colour
and tight stars, so the advisor requires full spectrum to beat visible by 15%
before recommending it. That reproduces the standard advice (always put a UV/IR
cut on a modified camera) from the photon budget rather than from folklore.

On an emission target the same arithmetic runs the other way and is not close:
a duo-band passes the nebula's line flux while cutting continuum sky ~20x, and
because both broadband modes and the sky scale together, that margin is the
same at Bortle 8 as at Bortle 3.

Mode choice maximizes SNR only — it does not know that a broadband filter also
captures colour in one shot, or that narrowband needs far more total
integration time. Use `--filters` to constrain it to what you'll really use.

### Smart telescopes

Aperture and focal length are the makers' published figures; the sensor's
usable pixel count is cross-checked against each maker's quoted field of view,
which a test pins (Seestar 1.29 x 0.73 deg, DWARF II 3.0 x 1.7, DWARF 3 2.9 x
1.6, DWARF mini 2.1 x 1.2, eQuinox 2 45' x 34').

Where an instrument states a longest exposure it will take, that ceiling is
modelled: the DWARF mini stops at 90 s, and under a dark sky its dual-band
optimum runs past that, so the plan says you are read-noise limited and should
shoot more subs rather than longer ones. An unknown ceiling stays unknown
rather than being guessed at as "unlimited". Read noise and QE are nominal for the sensor rather
than measured for your unit — override with `--read-noise` / `--qe`.

Their built-in dual-band filters are modelled as *wide* (~2x20 nm), not as the
7 nm filter a filter-wheel rig would use, because that is what these
instruments ship. It costs about half the narrowband advantage: roughly 2.5x a
visible train on an emission target rather than 4x. Worth knowing before
comparing a Seestar's numbers against a cooled-camera rig's.

## Web page

`web/` builds a single self-contained HTML file with the same model ported to
JavaScript, so site, date, sky class, telescope, corrector, camera, timezone
and unit system are all live controls. The site field takes a name, a pasted
position or a maps link, and there is a **Use my location** button — browser
geolocation, which needs a secure page (https or localhost) and the viewer's
permission, and says which of the two is missing when it fails (the browser owns the tz database, so DST
and zone abbreviations come out right without shipping a table):

```bash
python web/build.py            # -> web/dist/tonight.html
python web/shoot.py            # render it in Chromium, fail on any error
```

The port is not trusted on faith. `web/dump_reference.py` computes plans with
the Python engine across eight sites, dates and rigs, and `node web/validate.mjs`
checks the JavaScript against them target by target — ranking order, mode,
sub length and SkyQual must match, and the ephemeris agreement is reported as
measured maxima (currently 0.15 deg on the moon, 0.008 deg on targets).

## Roadmap

- Hα survey sampling (hips2fits / Finkbeiner map) so filter advice uses the
  actual emission strength at the target's coordinates
- Spectral sky model (airglow lines vs. continuum), which would let filter
  choice change the moon's relative cost as it does in reality
- Compressed-XISF support, OSC Bayer-aware statistics
- Multi-night project planning
- Serve the web page from the Python core instead of a static build, so the
  catalog and the site search are live rather than bundled

## Disclaimers

Camera specs and catalog data are approximate, bundled for convenience —
verify against your own sensor's published curves. Sky model assumes a flat
sky spectrum; treat outputs as planning guidance, not photometry.
