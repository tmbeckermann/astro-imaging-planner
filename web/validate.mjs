/* Hold webcore.js to the Python engine.
 *
 *   python web/export_data.py && python web/dump_reference.py && node web/validate.mjs
 *
 * Every number the page shows is checked against astropy + astroplanner for
 * eight sites/dates/rigs: the darkness window, the moon track, then every
 * ranked target's altitude, moon separation, sky quality, recommended mode and
 * sub length. Ephemeris tolerances are in degrees and reported as measured
 * maxima, so a regression shows up as a number moving, not as a pass/fail flip.
 */

import { readFileSync } from "node:fs";
import { buildNight, optimalSub, rankTargets } from "./webcore.js";

const data = JSON.parse(readFileSync(new URL("./data.json", import.meta.url)));
const reference = JSON.parse(readFileSync(new URL("./reference.json", import.meta.url)));

const cameras = Object.fromEntries(data.cameras.map((c) => [c.key, c]));
const filters = data.filters;
const targets = data.targets;

const TOL = {
  moonAltDeg: 0.25,     // low-precision lunar theory vs astropy
  maxAltDeg: 0.1,       // targets are fixed stars; only sidereal time matters
  moonSepDeg: 0.3,
  darkHours: 0.11,      // one 6-minute grid step
  skyQualityRel: 0.02,
  scoreRel: 0.02,
  subExactRel: 0.02,
};

const GRID_STEP_HOURS = 0.1;   // the 6-minute sampling grid
const boundaryCases = [];
let failures = 0;
const worst = { moonAlt: 0, maxAlt: 0, moonSep: 0, skyQuality: 0, score: 0, illum: 0, subExact: 0 };

function fail(msg) {
  failures++;
  if (failures <= 25) console.error("  FAIL " + msg);
}

function track(key, value) {
  worst[key] = Math.max(worst[key], Math.abs(value));
}

for (const ref of reference) {
  const camera = cameras[ref.camera];
  const night = buildNight(ref.date, ref.lat, ref.lon);

  if (night.darknessKind !== ref.night.darkness_kind) {
    fail(`${ref.label}: darkness kind ${night.darknessKind} != ${ref.night.darkness_kind}`);
  }
  if (Math.abs(night.darkHours - ref.night.dark_hours) > TOL.darkHours) {
    fail(`${ref.label}: dark hours ${night.darkHours.toFixed(2)} != ${ref.night.dark_hours.toFixed(2)}`);
  }
  track("illum", night.illumination - ref.night.illumination);
  if (Math.abs(night.illumination - ref.night.illumination) > 0.01) {
    fail(`${ref.label}: illumination ${night.illumination.toFixed(3)} != ${ref.night.illumination.toFixed(3)}`);
  }
  for (let i = 0; i < ref.night.moon_alt.length; i++) {
    const d = night.moonAlt[i] - ref.night.moon_alt[i];
    track("moonAlt", d);
    if (Math.abs(d) > TOL.moonAltDeg) {
      fail(`${ref.label}: moon alt[${i}] ${night.moonAlt[i].toFixed(2)} != ${ref.night.moon_alt[i].toFixed(2)}`);
      break;
    }
  }

  const ranked = rankTargets(night, {
    camera,
    focalLengthMm: ref.focal_length_mm,
    apertureMm: ref.aperture_mm,
    bortle: ref.bortle,
    targets,
    filters,
    allowedFilterKeys: ref.allowed_filters ? new Set(ref.allowed_filters) : null,
  });
  const byId = Object.fromEntries(ranked.map((r) => [r.target.id, r]));

  if (ranked.length !== ref.targets.length) {
    fail(`${ref.label}: ${ranked.length} targets ranked, Python got ${ref.targets.length}`);
  }

  for (const rt of ref.targets) {
    const got = byId[rt.id];
    if (!got) { fail(`${ref.label}/${rt.id}: missing from the JS ranking`); continue; }

    track("maxAlt", got.maxAltDeg - rt.max_alt);
    if (Math.abs(got.maxAltDeg - rt.max_alt) > TOL.maxAltDeg) {
      fail(`${ref.label}/${rt.id}: max alt ${got.maxAltDeg.toFixed(2)} != ${rt.max_alt.toFixed(2)}`);
    }
    track("moonSep", got.meanMoonSepDeg - rt.mean_moon_sep);
    if (Math.abs(got.meanMoonSepDeg - rt.mean_moon_sep) > TOL.moonSepDeg) {
      fail(`${ref.label}/${rt.id}: moon sep ${got.meanMoonSepDeg.toFixed(2)} != ${rt.mean_moon_sep.toFixed(2)}`);
    }
    const sqRel = (got.skyQuality - rt.sky_quality) / rt.sky_quality;
    track("skyQuality", sqRel);
    if (Math.abs(sqRel) > TOL.skyQualityRel) {
      fail(`${ref.label}/${rt.id}: sky quality ${got.skyQuality.toFixed(3)} != ${rt.sky_quality.toFixed(3)}`);
    }
    // A target grazing the 30-degree floor can gain or lose one 6-minute
    // sample on an 0.008-degree altitude difference, which moves its hours and
    // therefore its score. That is the grid quantising, not the model
    // disagreeing, so compare the rate rather than the total when it happens.
    const hourGap = Math.abs(got.usableHours - rt.usable_hours);
    if (hourGap > GRID_STEP_HOURS + 1e-9) {
      fail(`${ref.label}/${rt.id}: usable hours ${got.usableHours.toFixed(2)} != ${rt.usable_hours.toFixed(2)}`);
    } else if (hourGap > 1e-9) {
      boundaryCases.push(`${ref.label}/${rt.id}`);
    }
    const scaled = hourGap > 1e-9 ? (got.score / got.usableHours) : got.score;
    const refScaled = hourGap > 1e-9 ? (rt.score / rt.usable_hours) : rt.score;
    const scRel = (scaled - refScaled) / Math.max(refScaled, 1e-9);
    track("score", scRel);
    if (Math.abs(scRel) > TOL.scoreRel) {
      fail(`${ref.label}/${rt.id}: score ${got.score.toFixed(3)} != ${rt.score.toFixed(3)}`);
    }
    if (got.modeAdvice.recommended !== rt.mode) {
      fail(`${ref.label}/${rt.id}: mode ${got.modeAdvice.recommended} != ${rt.mode}`);
    }
    if (got.modeAdvice.scores[got.modeAdvice.recommended].filterKey !== rt.mode_filter) {
      fail(`${ref.label}/${rt.id}: mode filter mismatch`);
    }
    // The sub length is the exact optimum rounded up to a rung of the standard
    // ladder, so a target whose optimum lands within a hair of a rung can round
    // either way on a 0.1% difference in sky rate. Check the continuous value
    // tightly, and only demand the rung match when the optimum is not sitting
    // on the boundary.
    const mode = got.modeAdvice.scores[got.modeAdvice.recommended];
    const exact = optimalSub(camera.read_noise_e, mode.skyEPerS).optimal;
    const exactRel = (exact - rt.sub_exact_s) / rt.sub_exact_s;
    track("subExact", exactRel);
    if (Math.abs(exactRel) > TOL.subExactRel) {
      fail(`${ref.label}/${rt.id}: exact sub ${exact.toFixed(2)}s != ${rt.sub_exact_s.toFixed(2)}s`);
    }
    if (mode.recommendedSubS !== rt.sub_s) {
      const straddles = Math.min(mode.recommendedSubS, rt.sub_s) >= Math.min(exact, rt.sub_exact_s);
      if (straddles && Math.abs(exactRel) < 0.01) {
        boundaryCases.push(`${ref.label}/${rt.id} (sub rung ${rt.sub_s}s vs ${mode.recommendedSubS}s)`);
      } else {
        fail(`${ref.label}/${rt.id}: sub ${mode.recommendedSubS}s != ${rt.sub_s}s`);
      }
    }
    for (const [k, avail] of Object.entries(rt.mode_available)) {
      if (got.modeAdvice.scores[k].available !== avail) {
        fail(`${ref.label}/${rt.id}: mode ${k} availability mismatch`);
      }
    }
    if (got.suggestedFilter.key !== rt.suggested_filter) {
      fail(`${ref.label}/${rt.id}: optimal filter ${got.suggestedFilter.key} != ${rt.suggested_filter}`);
    }
  }

  // The ranking order itself, not just the per-target numbers.
  const jsOrder = ranked.map((r) => r.target.id).join(",");
  const pyOrder = ref.targets.map((r) => r.id).join(",");
  if (jsOrder !== pyOrder) {
    const firstDiff = ranked.findIndex((r, i) => r.target.id !== ref.targets[i]?.id);
    fail(`${ref.label}: ranking order diverges at #${firstDiff + 1} ` +
         `(JS ${ranked[firstDiff]?.target.id} vs Python ${ref.targets[firstDiff]?.id})`);
  }
}

const checked = reference.reduce((n, r) => n + r.targets.length, 0);
console.log(`checked ${reference.length} cases / ${checked} ranked targets`);
console.log("worst disagreement vs astropy + astroplanner:");
console.log(`  moon altitude   ${worst.moonAlt.toFixed(3)} deg`);
console.log(`  target altitude ${worst.maxAlt.toFixed(3)} deg`);
console.log(`  moon separation ${worst.moonSep.toFixed(3)} deg`);
console.log(`  illumination    ${(worst.illum * 100).toFixed(2)} %`);
console.log(`  sky quality     ${(worst.skyQuality * 100).toFixed(3)} %`);
console.log(`  score           ${(worst.score * 100).toFixed(3)} %`);
console.log(`  sub optimum     ${(worst.subExact * 100).toFixed(3)} %`);
if (boundaryCases.length) {
  console.log(`\n${boundaryCases.length} target(s) landed on a quantisation boundary (the ` +
              `6-minute grid or a sub-length rung) and differ by one step: ${boundaryCases.join(", ")}`);
}

if (failures) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");
