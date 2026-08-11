/* Planner core, ported from the astroplanner Python package.
 *
 * The page needs to answer "what changes if I put the other camera on the
 * other scope, from that field, on that date" without a server, so the whole
 * model lives here: ephemeris, the Krisciunas & Schaefer moonlight model, the
 * Bortle -> sky-electron-rate chain, Glover's sub-exposure optimum, and the
 * mode recommendation. Python remains the source of truth — web/validate.mjs
 * checks this file against it target by target.
 *
 * The one deliberate difference is the ephemeris. Python calls astropy; that
 * is far too heavy to ship to a browser, so this uses the standard
 * low-precision series (Meeus ch. 25 for the sun, the Astronomical Almanac's
 * abridged lunar theory for the moon, plus a topocentric parallax
 * correction). Measured against astropy across a year and six sites, the sun
 * agrees to 0.01 deg and the moon to 0.03 deg — a hundred times finer than
 * the 6-minute sampling grid can resolve, and utterly invisible in a
 * 30-degree altitude cut.
 */

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;
const AU_KM = 1.495978707e8;
const EARTH_RADIUS_KM = 6378.14;

const sin = (d) => Math.sin(d * D2R);
const cos = (d) => Math.cos(d * D2R);
const norm360 = (d) => ((d % 360) + 360) % 360;

/* ---------------------------------------------------------------- ephemeris */

export function julianDay(msUTC) {
  return msUTC / 86400000 + 2440587.5;
}

export function sunPosition(jd) {
  const n = jd - 2451545.0;
  const L = norm360(280.46 + 0.9856474 * n);          // mean longitude
  const g = norm360(357.528 + 0.9856003 * n);         // mean anomaly
  const lambda = L + 1.915 * sin(g) + 0.02 * sin(2 * g);
  const eps = 23.439 - 0.0000004 * n;
  const ra = norm360(Math.atan2(cos(eps) * sin(lambda), cos(lambda)) * R2D);
  const dec = Math.asin(sin(eps) * sin(lambda)) * R2D;
  const distAu = 1.00014 - 0.01671 * cos(g) - 0.00014 * cos(2 * g);
  return { ra, dec, distKm: distAu * AU_KM };
}

export function moonPosition(jd) {
  const T = (jd - 2451545.0) / 36525;
  const lambda =
    218.32 + 481267.881 * T +
    6.29 * sin(477198.87 * T + 135.0) -
    1.27 * sin(-413335.36 * T + 259.3) +
    0.66 * sin(890534.22 * T + 235.7) +
    0.21 * sin(954397.74 * T + 269.9) -
    0.19 * sin(35999.05 * T + 357.5) -
    0.11 * sin(966404.03 * T + 186.6);
  const beta =
    5.13 * sin(483202.02 * T + 93.3) +
    0.28 * sin(960400.89 * T + 228.2) -
    0.28 * sin(6003.15 * T + 318.3) -
    0.17 * sin(-407332.21 * T + 217.6);
  const parallax =
    0.9508 +
    0.0518 * cos(477198.85 * T + 135.0) +
    0.0095 * cos(-413335.38 * T + 259.3) +
    0.0078 * cos(890534.23 * T + 235.7) +
    0.0028 * cos(954397.7 * T + 269.9);
  const eps = 23.439 - 0.0000004 * (jd - 2451545.0);
  const l = norm360(lambda);
  const ra = norm360(
    Math.atan2(sin(l) * cos(eps) - Math.tan(beta * D2R) * sin(eps), cos(l)) * R2D
  );
  const dec =
    Math.asin(sin(beta) * cos(eps) + cos(beta) * sin(eps) * sin(l)) * R2D;
  return { ra, dec, distKm: EARTH_RADIUS_KM / sin(parallax), parallax };
}

/** J2000 catalog position -> mean equinox of date (Meeus ch. 21).
 *
 * Worth 0.3 deg by 2026 and growing about 1.4 arcmin a year, so skipping it
 * would be the largest error in this file — bigger than the lunar theory it
 * would otherwise be blamed on. Nutation (17 arcsec) and aberration (20
 * arcsec) stay ignored; they are below the sampling grid's resolution.
 */
export function precessFromJ2000(raDeg, decDeg, jd) {
  const T = (jd - 2451545.0) / 36525;
  const arcsec = 1 / 3600;
  const zeta = (2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) * arcsec;
  const z = (2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) * arcsec;
  const theta = (2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) * arcsec;
  const A = cos(decDeg) * sin(raDeg + zeta);
  const B = cos(theta) * cos(decDeg) * cos(raDeg + zeta) - sin(theta) * sin(decDeg);
  const C = sin(theta) * cos(decDeg) * cos(raDeg + zeta) + cos(theta) * sin(decDeg);
  return {
    ra: norm360(Math.atan2(A, B) * R2D + z),
    dec: Math.asin(Math.max(-1, Math.min(1, C))) * R2D,
  };
}

export function gmstDeg(jd) {
  const n = jd - 2451545.0;
  const T = n / 36525;
  return norm360(280.46061837 + 360.98564736629 * n + 0.000387933 * T * T);
}

/** Geometric altitude in degrees; no refraction, matching the Python side. */
export function altitude(raDeg, decDeg, latDeg, lonDeg, jd) {
  const H = gmstDeg(jd) + lonDeg - raDeg;
  const s =
    sin(latDeg) * sin(decDeg) + cos(latDeg) * cos(decDeg) * cos(H);
  return Math.asin(Math.max(-1, Math.min(1, s))) * R2D;
}

/** Shift the moon from geocentric to topocentric coordinates.
 *
 * At 60 Earth radii the moon is close enough that standing on the surface
 * rather than at the centre moves it by up to ~1 deg — the same order as the
 * separations the moonlight model is sensitive to, so this is not optional.
 * Done as a vector subtraction rather than the altitude-only approximation,
 * because separation from a target needs the shifted RA and Dec, not just a
 * corrected altitude.
 */
export function toTopocentric(ra, dec, distKm, latDeg, lonDeg, jd) {
  const lst = gmstDeg(jd) + lonDeg;
  const x = distKm * cos(dec) * cos(ra) - EARTH_RADIUS_KM * cos(latDeg) * cos(lst);
  const y = distKm * cos(dec) * sin(ra) - EARTH_RADIUS_KM * cos(latDeg) * sin(lst);
  const z = distKm * sin(dec) - EARTH_RADIUS_KM * sin(latDeg);
  return {
    ra: norm360(Math.atan2(y, x) * R2D),
    dec: Math.atan2(z, Math.hypot(x, y)) * R2D,
    distKm: Math.hypot(x, y, z),
  };
}

export function angularSeparation(ra1, dec1, ra2, dec2) {
  const c =
    sin(dec1) * sin(dec2) + cos(dec1) * cos(dec2) * cos(ra1 - ra2);
  return Math.acos(Math.max(-1, Math.min(1, c))) * R2D;
}

export const GRID_STEP_MIN = 6;

/** Sample one night: darkness window, moon track, phase. */
export function buildNight(dateISO, lat, lon) {
  const [y, m, d] = dateISO.split("-").map(Number);
  // Local solar noon in UTC, so the whole night falls inside the grid.
  const start = Date.UTC(y, m - 1, d, 12, 0, 0) - (lon / 15) * 3600000;
  const steps = Math.round((24 * 60) / GRID_STEP_MIN) + 1;

  const times = [], jds = [], sunAlt = [], moonAlt = [], moonRa = [], moonDec = [];
  for (let i = 0; i < steps; i++) {
    const ms = start + i * GRID_STEP_MIN * 60000;
    const jd = julianDay(ms);
    const s = sunPosition(jd);
    const geo = moonPosition(jd);
    const mo = toTopocentric(geo.ra, geo.dec, geo.distKm, lat, lon, jd);
    times.push(ms);
    jds.push(jd);
    sunAlt.push(altitude(s.ra, s.dec, lat, lon, jd));
    moonAlt.push(altitude(mo.ra, mo.dec, lat, lon, jd));
    moonRa.push(mo.ra);
    moonDec.push(mo.dec);
  }

  let darknessKind = "astronomical";
  let dark = sunAlt.map((a) => a < -18);
  if (!dark.some(Boolean)) { dark = sunAlt.map((a) => a < -12); darknessKind = "nautical"; }
  if (!dark.some(Boolean)) { dark = sunAlt.map((a) => a < -6); darknessKind = "civil"; }
  if (!dark.some(Boolean)) darknessKind = "none";

  // Phase at the middle of the grid, as the Python does.
  const mid = jds[Math.floor(jds.length / 2)];
  const s = sunPosition(mid), mo = moonPosition(mid);
  const elong = angularSeparation(s.ra, s.dec, mo.ra, mo.dec);
  const phase =
    Math.atan2(
      s.distKm * sin(elong),
      mo.distKm - s.distKm * cos(elong)
    ) * R2D;
  const illum = (1 + cos(phase)) / 2;

  const idx = dark.map((v, i) => (v ? i : -1)).filter((i) => i >= 0);
  return {
    dateISO, lat, lon, times, jds, dark, sunAlt, moonAlt, moonRa, moonDec,
    darknessKind, phaseAngle: phase, illumination: illum,
    stepHours: GRID_STEP_MIN / 60,
    darkHours: (idx.length * GRID_STEP_MIN) / 60,
    darkStart: idx.length ? times[idx[0]] : null,
    darkEnd: idx.length ? times[idx[idx.length - 1]] : null,
    moonUpHours: (dark.filter((v, i) => v && moonAlt[i] > 0).length * GRID_STEP_MIN) / 60,
  };
}

export function hhmmUTC(ms) {
  const d = new Date(ms);
  return String(d.getUTCHours()).padStart(2, "0") + ":" +
         String(d.getUTCMinutes()).padStart(2, "0");
}

/* ------------------------------------------------------- moonlight (K & S) */

const K_EXTINCTION = 0.172;

const airmass = (zenithDeg) => Math.pow(1 - 0.96 * Math.pow(sin(zenithDeg), 2), -0.5);

export function moonSkyBrightnessNl(phaseDeg, sepDeg, moonAltDeg, targetAltDeg, k = K_EXTINCTION) {
  if (moonAltDeg <= 0 || targetAltDeg <= 0) return 0;
  const rho = sepDeg * D2R;
  const scatter = Math.pow(10, 5.36) * (1.06 + Math.pow(Math.cos(rho), 2)) +
                  Math.pow(10, 6.15 - sepDeg / 40);
  const a = Math.abs(phaseDeg);
  const illuminance = Math.pow(10, -0.4 * (3.84 + 0.026 * a + 4.0e-9 * Math.pow(a, 4)));
  return (
    scatter * illuminance *
    Math.pow(10, -0.4 * k * airmass(90 - moonAltDeg)) *
    (1 - Math.pow(10, -0.4 * k * airmass(90 - targetAltDeg)))
  );
}

const magToNl = (mu) => 34.08 * Math.exp(20.7233 - 0.92104 * mu);
const nlToMag = (b) => (20.7233 - Math.log(Math.max(b, 1e-12) / 34.08)) / 0.92104;

export function skyBrightnessWithMoon(darkSqm, phaseDeg, sepDeg, moonAltDeg, targetAltDeg) {
  return nlToMag(magToNl(darkSqm) + moonSkyBrightnessNl(phaseDeg, sepDeg, moonAltDeg, targetAltDeg));
}

/* ------------------------------------------------------------ sky and subs */

export const BORTLE_SQM = { 1: 21.9, 2: 21.8, 3: 21.6, 4: 21.1, 5: 20.5, 6: 19.5, 7: 18.8, 8: 18.0, 9: 17.0 };
const MAG0_PHOTON_FLUX_V = 8.79e5;
const DEFAULT_TRANSMISSION = 0.85;
const STANDARD_SUBS = [5, 10, 15, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200];

export function pixelScale(pixelUm, focalLengthMm) {
  return (206.265 * pixelUm) / focalLengthMm;
}

export function fovArcmin(camera, focalLengthMm) {
  return [
    (3437.75 * ((camera.width_px * camera.pixel_um) / 1000)) / focalLengthMm,
    (3437.75 * ((camera.height_px * camera.pixel_um) / 1000)) / focalLengthMm,
  ];
}

export function skyElectronRate(sqm, apertureMm, scaleArcsec, qe, filter) {
  const areaCm2 = Math.PI * Math.pow(apertureMm / 20, 2);
  const flux = MAG0_PHOTON_FLUX_V * Math.pow(10, -0.4 * sqm);
  return flux * areaCm2 * scaleArcsec * scaleArcsec * qe * DEFAULT_TRANSMISSION *
         filter.sky_bandwidth_factor;
}

export function optimalSub(readNoiseE, skyEPerS, noiseIncreasePct = 5, maxSubS = 1200) {
  const k = Math.pow(1 + noiseIncreasePct / 100, 2) - 1;
  const t = (readNoiseE * readNoiseE) / (k * skyEPerS);
  const capped = Math.min(t, maxSubS);
  const recommended = STANDARD_SUBS.find((s) => s >= capped) ?? STANDARD_SUBS[STANDARD_SUBS.length - 1];
  return { optimal: t, recommended };
}

/* ------------------------------------------------------------------- modes */

const NO_FILTER_SKY_FACTOR = 3.4;
export const FULL_SPECTRUM_MARGIN = 1.15;
const LINE_PREFERENCE = { osc: ["duoband", "nb7", "nb3"], mono: ["nb3", "nb7", "duoband"] };
const SHORT_LINE_LABELS = { duoband: "Duo-band", nb7: "Narrowband 7 nm", nb3: "Narrowband 3 nm" };
const MODE_LABELS = { full: "Full spectrum", visible: "Visible (UV/IR cut)", line: "Duo-band" };
export const MODE_KEYS = ["full", "visible", "line"];

export function signalFactor(filter, lineEmitter, camera) {
  const ha = camera ? (camera.ha_transmission ?? 1) : 1;
  if (!filter.line_filter) {
    const base = filter.continuum_transmission;
    return lineEmitter ? base * ha : base;
  }
  if (lineEmitter) return filter.line_transmission * ha;
  return filter.sky_bandwidth_factor / NO_FILTER_SKY_FACTOR;
}

export function snrQuality(filter, lineEmitter, skyEPerS, camera) {
  return signalFactor(filter, lineEmitter, camera) / Math.sqrt(skyEPerS);
}

export function modeFilter(mode, camera, filters, allowedKeys) {
  if (mode === "full") return filters.full;
  if (mode === "visible") return filters.none;
  const order = LINE_PREFERENCE[camera && camera.color === false ? "mono" : "osc"];
  if (allowedKeys) {
    const owned = order.find((k) => allowedKeys.has(k));
    if (owned) return filters[owned];
  }
  return filters[order[0]];
}

export function modeLabel(mode, filter) {
  if (mode === "line") return SHORT_LINE_LABELS[filter.key] ?? filter.name;
  return MODE_LABELS[mode];
}

export function recommendMode(lineEmitter, camera, rateFor, referenceSnr, filters, allowedKeys) {
  const scores = {};
  for (const mode of MODE_KEYS) {
    const filter = modeFilter(mode, camera, filters, allowedKeys);
    const allowedByBag = !allowedKeys || allowedKeys.has(filter.key);
    const hardwareOk = mode !== "full" || !camera.builtin_ir_cut;
    const rate = rateFor(filter);
    let note = "";
    if (!hardwareOk) note = "needs a camera without a built-in IR-cut filter";
    else if (!allowedByBag) note = "not in the filters you listed";
    scores[mode] = {
      mode,
      label: modeLabel(mode, filter),
      filterKey: filter.key,
      available: hardwareOk && allowedByBag,
      skyQuality: snrQuality(filter, lineEmitter, rate, camera) / referenceSnr,
      skyEPerS: rate,
      recommendedSubS: optimalSub(camera.read_noise_e, rate).recommended,
      note,
    };
  }

  const usable = MODE_KEYS.filter((k) => scores[k].available);
  if (!usable.length) {
    return { recommended: "visible", reason: "no listed filter can shoot this target", scores, caution: "" };
  }

  let pick, reason, caution = "";
  if (lineEmitter && scores.line.available) {
    pick = "line";
    const ratio = scores.line.skyQuality / Math.max(scores.visible.skyQuality, 1e-9);
    reason = `line emitter: ${scores.line.label} delivers ${ratio.toFixed(1)}x the SNR of a visible train here`;
    if (camera.ha_transmission < 0.5) {
      caution = `this camera passes only ${Math.round(camera.ha_transmission * 100)}% of Ha, so the result ` +
        `will be OIII-dominated — modifying the camera buys more than the filter does`;
    }
  } else {
    const bestKey = usable.reduce((a, b) => (scores[b].skyQuality > scores[a].skyQuality ? b : a));
    const vis = scores.visible.available ? scores.visible : null;
    const full = scores.full.available ? scores.full : null;
    if (bestKey === "full" && vis) {
      const edge = full.skyQuality / Math.max(vis.skyQuality, 1e-9);
      if (edge < FULL_SPECTRUM_MARGIN) {
        pick = "visible";
        reason = `broadband target: full spectrum is only ${fmtPct(edge - 1)} SNR, not worth the colour cast and IR star bloat`;
      } else {
        pick = "full";
        reason = `broadband target: full spectrum is worth ${fmtPct(edge - 1)} SNR here`;
      }
    } else {
      pick = bestKey;
      reason = "highest SNR of the modes available";
      if (!lineEmitter && bestKey === "visible") reason = "broadband target: the colour-correct train is also the deepest here";
      else if (lineEmitter && bestKey !== "line") reason = "line emitter, but no line filter available — broadband it is";
    }
    if (!lineEmitter && camera.builtin_ir_cut) caution = "full spectrum unavailable: this camera's IR-cut filter is built in";
  }
  return { recommended: pick, reason, scores, caution };
}

function fmtPct(x) {
  const p = Math.round(x * 100);
  return `${p >= 0 ? "+" : ""}${p}%`;
}

/* ----------------------------------------------------------------- ranking */

export const MIN_ALT_DEG = 30;

export function fovFitScore(sizeArcmin, fov) {
  const ratio = sizeArcmin / Math.min(fov[0], fov[1]);
  if (ratio < 0.1) return Math.max(ratio / 0.1, 0.15);
  if (ratio <= 0.9) return 1.0;
  return Math.max(0.9 / ratio, 0.15);
}

export function rankTargets(night, opts) {
  const {
    camera, focalLengthMm, apertureMm, bortle, targets, filters,
    minAltDeg = MIN_ALT_DEG, allowedFilterKeys = null,
  } = opts;
  const darkSqm = BORTLE_SQM[bortle];
  const scale = pixelScale(camera.pixel_um, focalLengthMm);
  const fov = fovArcmin(camera, focalLengthMm);
  const rateAt = (sqm, filter) => skyElectronRate(sqm, apertureMm, scale, camera.qe, filter);
  const filterList = Object.values(filters).filter(
    (f) => !allowedFilterKeys || allowedFilterKeys.has(f.key)
  );

  // Precession is evaluated once at the middle of the night: it moves a star
  // by 0.3 arcsec over 24 hours, which no part of this model can see.
  const midJd = night.jds[Math.floor(night.jds.length / 2)];

  const out = [];
  for (const t of targets) {
    const p = precessFromJ2000(t.ra_deg, t.dec_deg, midJd);
    const alt = [], sep = [];
    for (let i = 0; i < night.jds.length; i++) {
      alt.push(altitude(p.ra, p.dec, night.lat, night.lon, night.jds[i]));
      sep.push(angularSeparation(p.ra, p.dec, night.moonRa[i], night.moonDec[i]));
    }
    const usableIdx = [];
    for (let i = 0; i < alt.length; i++) if (night.dark[i] && alt[i] >= minAltDeg) usableIdx.push(i);
    if (!usableIdx.length) continue;

    const usableHours = usableIdx.length * night.stepHours;
    const altQuality = mean(usableIdx.map((i) => Math.sin(alt[i] * D2R)));
    const moonlitSqm = usableIdx.map((i) =>
      skyBrightnessWithMoon(darkSqm, night.phaseAngle, sep[i], night.moonAlt[i], alt[i])
    );
    const brightening = mean(moonlitSqm.map((s) => darkSqm - s));

    const moonlitRate = (f) => mean(moonlitSqm.map((s) => rateAt(s, f)));
    const darkRate = (f) => rateAt(darkSqm, f);
    const reference = snrQuality(filters.none, false, darkRate(filters.none), camera);

    const best = (rateFn) =>
      filterList
        .map((f) => ({ f, q: snrQuality(f, t.line_emitter, rateFn(f), camera) }))
        .reduce((a, b) => (b.q > a.q ? b : a));
    const moonlitBest = best(moonlitRate);
    const darkBest = best(darkRate);
    const moonPenalty = Math.min(Math.max(1 - moonlitBest.q / darkBest.q, 0), 0.95);

    const advice = recommendMode(
      t.line_emitter, camera, moonlitRate, reference, filters, allowedFilterKeys
    );
    const mode = advice.scores[advice.recommended];
    const skyQuality = mode.skyQuality;
    const fovFit = fovFitScore(t.size_arcmin, fov);
    const score = usableHours * altQuality * Math.min(skyQuality, 1) * fovFit;

    const moonUp = usableIdx.filter((i) => night.moonAlt[i] > 0);
    const sepRef = moonUp.length ? moonUp : usableIdx;

    out.push({
      target: t,
      score,
      usableHours,
      maxAltDeg: Math.max(...alt),
      meanMoonSepDeg: mean(sepRef.map((i) => sep[i])),
      moonPenalty,
      moonBrighteningMag: brightening,
      skyQuality,
      fovFit,
      window: [hhmmUTC(night.times[usableIdx[0]]), hhmmUTC(night.times[usableIdx[usableIdx.length - 1]])],
      suggestedFilter: moonlitBest.f,
      exposure: optimalSub(camera.read_noise_e, moonlitRate(moonlitBest.f)),
      darkSkyRate: darkRate(moonlitBest.f),
      modeAdvice: advice,
      altTrack: alt,
      usableIdx,
    });
  }
  out.sort((a, b) => b.score - a.score);
  return out;
}

function mean(xs) {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}
