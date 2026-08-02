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
- **Filter advisor** — knows which targets are line emitters (Ha/OIII) and
  recommends a duo-band/narrowband filter when the moon is up or the sky is
  bright.
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

Plan tonight (St. Louis, Bortle 7, ASI533MC on an 80 mm f/6.25 refractor):

```bash
astroplanner plan --date 2026-08-02 --lat 38.6 --lon -90.2 --bortle 7 \
    --camera asi533mc --fl 500 --aperture 80 --top 5
```

Optimal sub length for a duo-band filter under that sky:

```bash
astroplanner exposure --bortle 7 --camera asi533mc --fl 500 --aperture 80 \
    --filter duoband
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

Reference lists: `astroplanner cameras`, `astroplanner filters`,
`astroplanner targets`. Unknown camera? Override with
`--read-noise` / `--qe` on any command.

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

## Roadmap

- Hα survey sampling (hips2fits / Finkbeiner map) so filter advice uses the
  actual emission strength at the target's coordinates
- Physical moonlight-scattering model (Krisciunas & Schaefer) instead of the
  heuristic penalty
- Compressed-XISF support, OSC Bayer-aware statistics
- Multi-night project planning and a small web UI

## Disclaimers

Camera specs and catalog data are approximate, bundled for convenience —
verify against your own sensor's published curves. Sky model assumes a flat
sky spectrum; treat outputs as planning guidance, not photometry.
