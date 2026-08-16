"""Command-line interface.

    astroplanner plan     --date 2026-08-02 --place "st louis" --bortle 7 \
                          --camera asi533mc --scope gt71
    astroplanner plan     --date 2026-08-02 --lat 38.6 --lon -90.2 --bortle 7 \
                          --camera asi533mc --fl 500 --aperture 80
    astroplanner exposure --bortle 7 --camera asi533mc --scope gt71 --filter duoband
    astroplanner analyze  Light_M31_120s.fits
    astroplanner log add  --date 2026-08-02 --target M31 --filter duoband --sub 120 --subs 90
    astroplanner log list
    astroplanner cameras | scopes | filters | targets | places <query>
"""

import argparse
import sys

from . import __version__
from .analyze import analyze_frame
from .catalog import load_targets
from .ephemeris import build_night
from .exposure import optimal_sub_exposure, stack_noise_penalty
from .filters import FILTERS, get_filter
from .geocode import resolve as resolve_place
from .geocode import search as search_places
from .integration_time import elbow_hours
from .scoring import rank_targets
from .sensors import CAMERAS, get_camera
from .sessionlog import DEFAULT_DB, SessionLog
from .sky import sky_electron_rate, sqm_from_bortle
from .telescopes import TELESCOPES, get_telescope
from .units import (
    DEFAULT_TZ,
    IMPERIAL,
    UNIT_SYSTEMS,
    format_aperture,
    format_elevation,
    format_focal_length,
    format_fov,
    get_zone,
    local_hhmm,
    zone_abbrev,
)


DEFAULT_CAMERA = "asi533mc"


def _rig_args(p: argparse.ArgumentParser):
    p.add_argument("--camera", help=f"camera key (see 'cameras'); default {DEFAULT_CAMERA}, "
                                    f"or the built-in sensor of an integrated scope")
    p.add_argument("--scope", help="telescope key (see 'scopes'); sets --fl and --aperture")
    p.add_argument("--corrector", help="reducer/corrector on the scope (see 'scopes')")
    p.add_argument("--fl", type=float, help="focal length, mm (overrides --scope)")
    p.add_argument("--aperture", type=float, help="aperture, mm (overrides --scope)")
    p.add_argument("--read-noise", type=float, help="override read noise, e-")
    p.add_argument("--qe", type=float, help="override QE, 0..1")


def _resolve_camera(args, scope=None):
    """An integrated instrument brings its own sensor; a tube does not."""
    key = args.camera
    if key is None:
        key = scope.fixed_camera if (scope and scope.integrated) else DEFAULT_CAMERA
    elif scope is not None and scope.integrated and key != scope.fixed_camera:
        print(f"Note: {scope.name} has its sensor bonded to it; using --camera {key} anyway, "
              f"which describes a rig that does not exist.", file=sys.stderr)
    cam = get_camera(key)
    if args.read_noise or args.qe:
        from dataclasses import replace
        cam = replace(
            cam,
            read_noise_e=args.read_noise or cam.read_noise_e,
            qe=args.qe or cam.qe,
        )
    return cam


def _resolve_optics(args) -> tuple[float, float, str]:
    """(focal_length_mm, aperture_mm, label) from --scope and/or --fl/--aperture."""
    label = ""
    fl = aperture = None
    scope = get_telescope(args.scope) if args.scope else None
    if scope:
        fl, aperture = scope.train(args.corrector)
        label = scope.name
        if args.corrector and args.corrector.lower() != "native":
            label += f" + {args.corrector}"
    elif args.corrector:
        raise SystemExit("--corrector needs --scope; with --fl just give the effective length")
    fl = args.fl if args.fl else fl
    aperture = args.aperture if args.aperture else aperture
    if fl is None or aperture is None:
        raise SystemExit(
            "Give a rig: either --scope KEY (see 'astroplanner scopes') or "
            "--fl MM --aperture MM."
        )
    return fl, aperture, label


def _resolve_filters(args, scope) -> list[str] | None:
    """What is actually in front of the sensor tonight.

    An integrated instrument has the filters its maker fitted and no others, so
    recommending a 3 nm narrowband for a Unistellar would be advice you cannot
    take. --filters still wins: it is you telling the planner what you own.
    """
    if args.filters:
        return args.filters.split(",")
    if scope is not None and scope.builtin_filters:
        return list(scope.builtin_filters)
    return None


def _presentation_args(p: argparse.ArgumentParser):
    p.add_argument("--tz", default=DEFAULT_TZ,
                   help=f"IANA timezone for displayed times (default {DEFAULT_TZ})")
    p.add_argument("--units", default=IMPERIAL, choices=UNIT_SYSTEMS,
                   help="unit system for elevation and aperture (default imperial)")


def _resolve_site(args) -> tuple[float, float, float, str]:
    """(lat, lon, elevation_m, label) from --place or --lat/--lon."""
    label = ""
    lat, lon, elev = args.lat, args.lon, args.elevation
    if args.place:
        place = resolve_place(args.place, online=not args.offline)
        lat = args.lat if args.lat is not None else place.lat
        lon = args.lon if args.lon is not None else place.lon
        elev = args.elevation if args.elevation is not None else place.elevation_m
        label = place.label
        if args.bortle is None and getattr(args, "sqm", None) is None:
            args.bortle = place.bortle_estimate
            how = {"measured": "measured at this site",
                   "typical": "typical for a city this size",
                   "estimated": "estimated from population"}[place.bortle_basis]
            print(f"Site: {place.label}  ({lat:+.2f}, {lon:+.2f}, "
                  f"{format_elevation(elev or 0.0, getattr(args, 'units', IMPERIAL))})  "
                  f"Bortle {args.bortle} [{how}]", file=sys.stderr)
    if lat is None or lon is None:
        raise SystemExit("Give a site: either --place NAME or --lat DEG --lon DEG.")
    if args.bortle is None and getattr(args, "sqm", None) is None:
        raise SystemExit("Give --bortle 1-9, or --sqm if you have a measured value "
                         "(or use --place, which suggests a class).")
    return lat, lon, (elev or 0.0), label


def cmd_plan(args) -> int:
    scope = get_telescope(args.scope) if args.scope else None
    cam = _resolve_camera(args, scope)
    fl, aperture, scope_label = _resolve_optics(args)
    lat, lon, elevation, site_label = _resolve_site(args)
    args.lat, args.lon, args.fl, args.aperture = lat, lon, fl, aperture
    ctx = build_night(args.date, lat, lon, elevation)
    if ctx.darkness_kind == "none":
        print("The sun never gets below -6 deg on this date at this site; no usable darkness.")
        return 1

    subset = None
    if args.type:
        wanted = {s.strip().lower() for s in args.type.split(",")}
        subset = [t for t in load_targets() if t.type in wanted]
        if not subset:
            print(f"No catalog targets of type(s) {args.type}. See 'astroplanner targets'.")
            return 1

    ranked = rank_targets(
        ctx, cam, args.fl, args.aperture, args.bortle,
        available_filters=_resolve_filters(args, scope),
        min_alt_deg=args.min_alt,
        targets=subset,
        max_sub_s=(scope.max_sub_s if scope and scope.max_sub_s else 1200.0),
        dark_sqm=args.sqm,
    )
    fov_w, fov_h = cam.fov_arcmin(args.fl)
    zone = get_zone(args.tz)
    clock = lambda t: local_hhmm(t.to_datetime(), zone)
    tzname = zone_abbrev(ctx.dark_start.to_datetime(), zone)
    where = f"{site_label}  ({args.lat:+.2f}, {args.lon:+.2f})" if site_label else \
            f"lat {args.lat:+.2f} lon {args.lon:+.2f}"
    sky = (f"SQM {args.sqm:.2f} mag/arcsec² [measured]" if args.sqm
           else f"Bortle {args.bortle} (SQM {sqm_from_bortle(args.bortle):.1f})")
    print(f"Night of {args.date}  |  {where}  |  {sky}")
    moon_hours = float((ctx.dark & (ctx.moon_alt_deg > 0)).sum()) * ctx.step_hours
    print(f"Darkness ({ctx.darkness_kind}): {clock(ctx.dark_start)}"
          f"-{clock(ctx.dark_end)} {tzname}  ({ctx.dark_hours:.1f} h)"
          f"  |  Moon {ctx.moon_illumination*100:.0f}% illuminated,"
          f" up {moon_hours:.1f} h of darkness")
    rig = (f"{cam.name}, {scope_label + ', ' if scope_label else ''}"
           f"{format_aperture(args.aperture, args.units)} at {format_focal_length(args.fl)} "
           f"f/{args.fl/args.aperture:.1f}")
    print(f"Rig: {rig}"
          f"  |  FoV {format_fov(fov_w, fov_h)}  |  {cam.pixel_scale(args.fl):.2f}\"/px")
    if scope is not None and scope.integrated:
        fitted = ", ".join(FILTERS[k].name for k in (scope.builtin_filters or ()))
        print(f"     Integrated instrument: sensor and filters are fixed — {fitted}"
              f"{'. ' + scope.spec_note if scope.spec_note else ''}")
        if scope.max_sub_s:
            print(f"     Longest sub it will take: {scope.max_sub_s:.0f}s")
        if scope.assumed:
            what = " and ".join(scope.assumed)
            fix = {"aperture": "--aperture", "focal length": "--fl",
                   "sensor": "--camera", "sensor pairing": "--read-noise / --qe"}
            how = ", ".join(sorted({fix.get(a, "--aperture / --fl") for a in scope.assumed}))
            print(f"     The {what} here is INFERRED, not published, and the numbers below "
                  f"depend on it. Override with {how}.")
    print()
    if not ranked:
        print(f"No catalog targets rise above {args.min_alt:.0f} deg during darkness tonight.")
        return 0

    hdr = (f"{'#':>2} {'ID':<8} {'Name':<26} {'Score':>5} {'Hrs':>4} {'MaxAlt':>6} "
           f"{'MoonSep':>7} {'MoonCost':>8} {'SkyQual':>7} {f'Window ({tzname})':<13} "
           f"{'Mode':<18} {'Sub':>5}")
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(ranked[: args.top], 1):
        cost = f"-{r.moon_brightening_mag:.2f}m" if r.moon_brightening_mag >= 0.005 else "     -"
        mode = r.mode_advice.best
        print(
            f"{i:>2} {r.target.id:<8} {r.target.name:<26} {r.score:>5.2f} "
            f"{r.usable_hours:>4.1f} {r.max_alt_deg:>5.0f}° {r.mean_moon_sep_deg:>6.0f}° {cost:>8} "
            f"{r.sky_quality:>7.2f} "
            f"{clock(ctx.times[r.window_idx[0]])}-{clock(ctx.times[r.window_idx[1]]):<7} "
            f"{mode.label:<18} {mode.recommended_sub_s:>4}s"
        )
    print()
    top = ranked[0]
    advice = top.mode_advice
    print(f"Best pick: {top.target.name} ({top.target.id}) — shoot it in "
          f"{advice.best.label}, {advice.best.recommended_sub_s}s subs "
          f"(sky {advice.best.sky_e_per_s:.2f} e-/px/s).")
    print(f"  Why: {advice.reason}.")
    if advice.best.sub_capped:
        print(f"  Its optimum is longer than this instrument's {scope.max_sub_s:.0f}s ceiling, so "
              f"you are read-noise limited: shoot more subs rather than longer ones.")
    if advice.caution:
        print(f"  Note: {advice.caution}.")
    print("  Mode comparison (SkyQual, 1.00 = visible train under a moonless sky here):")
    for key in ("full", "visible", "line"):
        m = advice.scores[key]
        mark = "->" if key == advice.recommended else "  "
        detail = f"{m.sky_quality:>6.2f}  {m.recommended_sub_s:>4}s subs" if m.available \
                 else f"{'  n/a':>6}  {m.note}"
        print(f"   {mark} {m.label:<20} {detail}")
    print(f"  Integration time (from catalog brightness{'; ' + top.brightness_caution if top.brightness_caution else ''}):")
    for pt in top.returns_table:
        print(f"     {pt.hours:>4.0f}h  SNR ~{pt.snr:>5.1f}   next hour: +{pt.next_hour_gain_pct:.0f}%")
    print(f"  Past {elbow_hours():.0f}h total, another hour buys less than 5% more SNR — "
          f"true for any target, gear or site once the sub length is fixed.")
    if top.moon_brightening_mag >= 0.05:
        print(f"Moonlight brightens its sky by {top.moon_brightening_mag:.2f} mag/arcsec² "
              f"({top.moon_penalty*100:.0f}% SNR cost vs. a moonless night; "
              f"dark-sky rate would be {top.dark_sky_rate:.2f} e-/px/s).")
    if args.filters or args.show_filter:
        print(f"SNR-optimal filter from the ones listed: {top.suggested_filter.name} "
              f"({top.sky_quality:.2f} SkyQual, {top.exposure.recommended_s}s subs).")
    print("SkyQual: achievable SNR, 1.00 = visible (UV/IR-cut) under a moonless sky at this site.")
    return 0


def cmd_exposure(args) -> int:
    scope = get_telescope(args.scope) if args.scope else None
    cam = _resolve_camera(args, scope)
    args.fl, args.aperture, scope_label = _resolve_optics(args)
    filt = get_filter(args.filter)
    if filt.needs_ir_cut_removed and cam.builtin_ir_cut:
        print(f"Note: {cam.name} has a built-in IR-cut filter, so '{filt.key}' is not a mode "
              f"it can shoot — showing the numbers anyway.", file=sys.stderr)
    sqm = args.sqm if args.sqm else sqm_from_bortle(args.bortle)
    scale = cam.pixel_scale(args.fl)
    if args.sky_rate:
        rate = args.sky_rate
        src = "measured"
    else:
        rate = sky_electron_rate(sqm, args.aperture, scale, cam.qe, filt)
        src = f"Bortle {args.bortle} (SQM {sqm:.1f})"
    res = optimal_sub_exposure(cam.read_noise_e, rate, args.noise_increase)

    print(f"Camera: {cam.name}  (read noise {cam.read_noise_e:.1f} e- @ {cam.gain_setting}, QE {cam.qe:.0%})")
    print(f"Optics: {scope_label + ', ' if scope_label else ''}"
          f"{format_aperture(args.aperture, args.units)} at {format_focal_length(args.fl)} "
          f"f/{args.fl/args.aperture:.1f}  ->  {scale:.2f}\"/px")
    print(f"Filter: {filt.name}")
    print(f"Sky:    {rate:.3f} e-/px/s  [{src}]")
    print()
    print(f"Optimal sub length : {res.optimal_s:.0f} s  (max {args.noise_increase:.0f}% stack-noise penalty)")
    print(f"Recommended setting: {res.recommended_s} s")
    print(f"Swamp factor       : sky must reach {res.swamp_factor:.1f}x read-noise variance per sub")
    for s in (60, 120, 300, 600):
        print(f"  {s:>4}s subs -> +{stack_noise_penalty(cam.read_noise_e, rate, s):.1f}% stack noise vs ideal")

    # Gain enters this model in exactly one place: read noise. The optimum goes
    # as read noise squared, so halving it quarters the sub length. Nothing else
    # here moves — QE is a property of the sensor, and full-well is not modelled
    # — so rather than invent a gain curve for cameras whose curves are not
    # published, show the sensitivity and let a measured figure drive it.
    print()
    print("Gain changes one thing here — read noise — and the optimum goes as its square:")
    for rn in sorted({0.5, 1.0, 1.5, 2.0, 3.0, round(cam.read_noise_e, 1)}):
        res_rn = optimal_sub_exposure(rn, rate, args.noise_increase)
        mark = "  <- this camera's default" if abs(rn - cam.read_noise_e) < 0.05 else ""
        print(f"  read noise {rn:>4.1f} e- -> optimum {res_rn.optimal_s:>6.0f}s "
              f"({res_rn.recommended_s}s){mark}")
    print("Measure yours from bias frames at the gain you use, then pass --read-noise.")
    return 0


def cmd_analyze(args) -> int:
    code = 0
    for path in args.files:
        try:
            st = analyze_frame(path, gain_e_per_adu=args.gain, offset_adu=args.offset, exptime_s=args.exptime)
        except Exception as e:
            print(f"{path}: ERROR {e}", file=sys.stderr)
            code = 1
            continue
        print(f"{st.path}  {st.shape}")
        print(f"  background {st.background_adu:.1f} ADU | noise {st.noise_adu:.2f} ADU"
              f" | bright signal {st.signal_adu:.1f} ADU | SNR {st.snr:.1f}"
              f" | saturated {st.saturated_frac*100:.2f}%")
        if st.sky_e_per_s is not None:
            print(f"  exposure {st.exptime_s:.0f}s -> measured sky {st.sky_e_per_s:.3f} e-/px/s"
                  f"   (feed to: astroplanner exposure --sky-rate {st.sky_e_per_s:.3f} ...)")
        elif st.exptime_s:
            print(f"  exposure {st.exptime_s:.0f}s (pass --gain e-/ADU to get sky e-/px/s)")
    return code


def cmd_cameras(_args) -> int:
    for key, c in sorted(CAMERAS.items()):
        stack = "mono" if c.mono else "OSC"
        ha = "" if c.ha_transmission >= 0.9 else f"  Ha {c.ha_transmission:.0%} (IR-cut built in)"
        print(f"{key:<10} {c.name:<40} {c.pixel_um}um  {c.width_px}x{c.height_px}  "
              f"RN {c.read_noise_e:.1f}e- @ {c.gain_setting}  QE {c.qe:.0%}  {stack}{ha}")
    return 0


def cmd_scopes(_args) -> int:
    # Alphabetical by name: you come here to find the scope you own, not to
    # browse the range of focal lengths.
    for key, t in sorted(TELESCOPES.items(), key=lambda kv: kv[1].name.lower()):
        extras = [label for label, _ in t.correctors if label != "native"]
        opts = f"  [{'; '.join(extras)}]" if extras else ""
        if t.integrated:
            fitted = "+".join(t.builtin_filters or ())
            cap = f"; max {t.max_sub_s:.0f}s" if t.max_sub_s else ""
            guess = f"; {'+'.join(t.assumed)} ASSUMED" if t.assumed else ""
            opts = f"  [sensor {t.fixed_camera}; filters {fitted}{cap}{guess}]"
        print(f"{key:<16} {t.name:<36} {t.aperture_mm:>6.1f} mm  {t.focal_length_mm:>6.1f} mm "
              f"f/{t.f_ratio:<4.1f} {t.kind}{opts}")
    return 0


def cmd_places(args) -> int:
    hits = search_places(args.query, limit=args.limit, online=not args.offline)
    if not hits:
        print(f"No place matched '{args.query}'.")
        return 1
    for p in hits:
        how = {"measured": "measured", "typical": "typical", "estimated": "est."}[p.bortle_basis]
        print(f"{p.label:<48} {p.lat:>7.2f} {p.lon:>8.2f}  "
              f"{format_elevation(p.elevation_m, args.units):>9}  "
              f"Bortle {p.bortle_estimate} ({how})  [{p.source}]")
    print()
    print("Use with: astroplanner plan --place \"<name>\" --date YYYY-MM-DD ...")
    print("Sky class: 'measured' at characterised observing sites, 'typical' for a city "
          "that size, 'est.' from population. Check lightpollutionmap.info; --bortle overrides.")
    return 0


def cmd_filters(_args) -> int:
    for key, f in FILTERS.items():
        kind = "line" if f.line_filter else "broadband"
        needs = "  (needs a modified camera)" if f.needs_ir_cut_removed else ""
        print(f"{key:<9} {f.name:<36} sky x{f.sky_bandwidth_factor:<5} moon x{f.moon_susceptibility:<5} "
              f"{kind}{needs}")
    return 0


def cmd_targets(_args) -> int:
    for t in load_targets():
        print(f"{t.id:<9} {t.name:<28} RA {t.ra_deg:7.2f}  Dec {t.dec_deg:+7.2f}  {t.size_arcmin:5.1f}'  "
              f"SB {t.surface_brightness_mag:5.1f}  {t.type}")
    return 0


def cmd_log_add(args) -> int:
    log = SessionLog(args.db)
    rid = log.add(args.date, args.target, args.filter, args.sub, args.subs, args.notes)
    total = f", {args.sub * args.subs / 60:.0f} min total" if args.sub and args.subs else ""
    print(f"Logged session #{rid}: {args.target} on {args.date}{total}")
    log.close()
    return 0


def cmd_log_list(args) -> int:
    log = SessionLog(args.db)
    entries = log.list(args.target)
    if not entries:
        print("No sessions logged yet.")
    for e in entries:
        total = f"{e.total_minutes:.0f} min" if e.total_minutes else "-"
        print(f"#{e.id:<4} {e.date}  {e.target:<12} {e.filter or '-':<9} "
              f"{e.subs or '-'} x {e.sub_s or '-'}s = {total}  {e.notes or ''}")
    log.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="astroplanner", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"astroplanner {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="rank tonight's best targets")
    sp.add_argument("--date", required=True, help="YYYY-MM-DD (evening of)")
    sp.add_argument("--place", help="site by name, e.g. --place \"cherry springs\"")
    sp.add_argument("--lat", type=float)
    sp.add_argument("--lon", type=float, help="east positive")
    sp.add_argument("--elevation", type=float, help="site elevation, m")
    sp.add_argument("--offline", action="store_true", help="never call the online geocoder")
    sp.add_argument("--bortle", type=int, choices=range(1, 10),
                    help="sky class 1-9; --place suggests one if omitted")
    sp.add_argument("--sqm", type=float,
                    help="measured zenith sky brightness, mag/arcsec^2 — overrides --bortle. "
                         "Read it off a light-pollution atlas or your own meter")
    _rig_args(sp)
    sp.add_argument("--filters", help="comma list of filters you own (default: all)")
    sp.add_argument("--show-filter", action="store_true",
                    help="also print the SNR-optimal filter, not just the mode")
    sp.add_argument("--type", help="only these target types, e.g. galaxy,cluster")
    _presentation_args(sp)
    sp.add_argument("--min-alt", type=float, default=30.0)
    sp.add_argument("--top", type=int, default=5)
    sp.set_defaults(func=cmd_plan)

    se = sub.add_parser("exposure", help="optimal sub-exposure length")
    se.add_argument("--bortle", type=int, default=5, choices=range(1, 10))
    se.add_argument("--sqm", type=float, help="measured SQM overrides --bortle")
    se.add_argument("--sky-rate", type=float, help="measured sky e-/px/s (from 'analyze') overrides sky model")
    se.add_argument("--filter", default="none")
    se.add_argument("--noise-increase", type=float, default=5.0, help="accepted stack-noise penalty %%")
    _presentation_args(se)
    _rig_args(se)
    se.set_defaults(func=cmd_exposure)

    sa = sub.add_parser("analyze", help="measure FITS/XISF sub-frames")
    sa.add_argument("files", nargs="+")
    sa.add_argument("--gain", type=float, help="e-/ADU (overrides header EGAIN)")
    sa.add_argument("--offset", type=float, help="bias/offset pedestal in ADU")
    sa.add_argument("--exptime", type=float, help="override exposure time, s")
    sa.set_defaults(func=cmd_analyze)

    sub.add_parser("cameras", help="list known cameras").set_defaults(func=cmd_cameras)
    sub.add_parser("scopes", help="list known telescopes").set_defaults(func=cmd_scopes)
    sub.add_parser("filters", help="list known filters").set_defaults(func=cmd_filters)
    sub.add_parser("targets", help="list the target catalog").set_defaults(func=cmd_targets)

    spl = sub.add_parser("places", help="search observing sites and towns")
    spl.add_argument("query")
    spl.add_argument("--limit", type=int, default=8)
    spl.add_argument("--offline", action="store_true", help="bundled gazetteer only")
    spl.add_argument("--units", default=IMPERIAL, choices=UNIT_SYSTEMS)
    spl.set_defaults(func=cmd_places)

    sl = sub.add_parser("log", help="session logger")
    slsub = sl.add_subparsers(dest="logcmd", required=True)
    sla = slsub.add_parser("add")
    sla.add_argument("--date", required=True)
    sla.add_argument("--target", required=True)
    sla.add_argument("--filter")
    sla.add_argument("--sub", type=float, help="sub length, s")
    sla.add_argument("--subs", type=int, help="number of subs")
    sla.add_argument("--notes")
    sla.add_argument("--db", default=str(DEFAULT_DB))
    sla.set_defaults(func=cmd_log_add)
    sll = slsub.add_parser("list")
    sll.add_argument("--target")
    sll.add_argument("--db", default=str(DEFAULT_DB))
    sll.set_defaults(func=cmd_log_list)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # `astroplanner scopes | head` closes the pipe on us. That is the
        # reader's choice, not an error, and a traceback about it is noise.
        try:
            sys.stdout.close()
        finally:
            return 0


if __name__ == "__main__":
    sys.exit(main())
