"""Command-line interface.

    astroplanner plan     --date 2026-08-02 --lat 38.6 --lon -90.2 --bortle 7 \
                          --camera asi533mc --fl 500 --aperture 80
    astroplanner exposure --bortle 7 --camera asi533mc --fl 500 --aperture 80 --filter duoband
    astroplanner analyze  Light_M31_120s.fits
    astroplanner log add  --date 2026-08-02 --target M31 --filter duoband --sub 120 --subs 90
    astroplanner log list
    astroplanner cameras | filters | targets
"""

import argparse
import sys

from . import __version__
from .analyze import analyze_frame
from .catalog import load_targets
from .ephemeris import build_night
from .exposure import optimal_sub_exposure, stack_noise_penalty
from .filters import FILTERS, get_filter
from .scoring import rank_targets
from .sensors import CAMERAS, get_camera
from .sessionlog import DEFAULT_DB, SessionLog
from .sky import sky_electron_rate, sqm_from_bortle


def _rig_args(p: argparse.ArgumentParser):
    p.add_argument("--camera", default="asi533mc", help="camera key (see 'cameras')")
    p.add_argument("--fl", type=float, required=True, help="focal length, mm")
    p.add_argument("--aperture", type=float, required=True, help="aperture, mm")
    p.add_argument("--read-noise", type=float, help="override read noise, e-")
    p.add_argument("--qe", type=float, help="override QE, 0..1")


def _resolve_camera(args):
    cam = get_camera(args.camera)
    if args.read_noise or args.qe:
        from dataclasses import replace
        cam = replace(
            cam,
            read_noise_e=args.read_noise or cam.read_noise_e,
            qe=args.qe or cam.qe,
        )
    return cam


def cmd_plan(args) -> int:
    cam = _resolve_camera(args)
    ctx = build_night(args.date, args.lat, args.lon, args.elevation)
    if ctx.darkness_kind == "none":
        print("The sun never gets below -6 deg on this date at this site; no usable darkness.")
        return 1

    ranked = rank_targets(
        ctx, cam, args.fl, args.aperture, args.bortle,
        available_filters=args.filters.split(",") if args.filters else None,
        min_alt_deg=args.min_alt,
    )
    fov_w, fov_h = cam.fov_arcmin(args.fl)
    print(f"Night of {args.date}  |  lat {args.lat:+.2f} lon {args.lon:+.2f}  |  Bortle {args.bortle}")
    print(f"Darkness ({ctx.darkness_kind}): {ctx.dark_start.strftime('%H:%M')}"
          f"-{ctx.dark_end.strftime('%H:%M')} UTC  ({ctx.dark_hours:.1f} h)"
          f"  |  Moon {ctx.moon_illumination*100:.0f}% illuminated")
    print(f"Rig: {cam.name}, {args.fl:.0f} mm f/{args.fl/args.aperture:.1f}"
          f"  |  FoV {fov_w:.0f}' x {fov_h:.0f}'  |  {cam.pixel_scale(args.fl):.2f}\"/px")
    print()
    if not ranked:
        print(f"No catalog targets rise above {args.min_alt:.0f} deg during darkness tonight.")
        return 0

    hdr = f"{'#':>2} {'ID':<8} {'Name':<26} {'Score':>5} {'Hrs':>4} {'MaxAlt':>6} {'MoonSep':>7} {'Window (UTC)':<13} {'Filter':<8} {'Sub':>5}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(ranked[: args.top], 1):
        print(
            f"{i:>2} {r.target.id:<8} {r.target.name:<26} {r.score:>5.2f} "
            f"{r.usable_hours:>4.1f} {r.max_alt_deg:>5.0f}° {r.mean_moon_sep_deg:>6.0f}° "
            f"{r.best_window[0]}-{r.best_window[1]:<7} {r.suggested_filter.key:<8} {r.exposure.recommended_s:>4}s"
        )
    print()
    top = ranked[0]
    print(f"Best pick: {top.target.name} ({top.target.id}) — {top.suggested_filter.name}, "
          f"{top.exposure.recommended_s}s subs "
          f"(sky {top.exposure.sky_e_per_s:.2f} e-/px/s, exact optimum {top.exposure.optimal_s:.0f}s).")
    if top.suggested_filter.line_filter:
        print("Duoband/narrowband suggested: line-emission target under moonlight/light pollution.")
    return 0


def cmd_exposure(args) -> int:
    cam = _resolve_camera(args)
    filt = get_filter(args.filter)
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
    print(f"Optics: {args.fl:.0f} mm f/{args.fl/args.aperture:.1f}  ->  {scale:.2f}\"/px")
    print(f"Filter: {filt.name}")
    print(f"Sky:    {rate:.3f} e-/px/s  [{src}]")
    print()
    print(f"Optimal sub length : {res.optimal_s:.0f} s  (max {args.noise_increase:.0f}% stack-noise penalty)")
    print(f"Recommended setting: {res.recommended_s} s")
    print(f"Swamp factor       : sky must reach {res.swamp_factor:.1f}x read-noise variance per sub")
    for s in (60, 120, 300, 600):
        print(f"  {s:>4}s subs -> +{stack_noise_penalty(cam.read_noise_e, rate, s):.1f}% stack noise vs ideal")
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
        print(f"{key:<10} {c.name:<38} {c.pixel_um}um  RN {c.read_noise_e:.1f}e- @ {c.gain_setting}  QE {c.qe:.0%}")
    return 0


def cmd_filters(_args) -> int:
    for key, f in FILTERS.items():
        kind = "line" if f.line_filter else "broadband"
        print(f"{key:<9} {f.name:<36} sky x{f.sky_bandwidth_factor:<5} moon x{f.moon_susceptibility:<5} {kind}")
    return 0


def cmd_targets(_args) -> int:
    for t in load_targets():
        print(f"{t.id:<9} {t.name:<28} RA {t.ra_deg:7.2f}  Dec {t.dec_deg:+7.2f}  {t.size_arcmin:5.1f}'  {t.type}")
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
    sp.add_argument("--lat", type=float, required=True)
    sp.add_argument("--lon", type=float, required=True, help="east positive")
    sp.add_argument("--elevation", type=float, default=0.0, help="site elevation, m")
    sp.add_argument("--bortle", type=int, required=True, choices=range(1, 10))
    _rig_args(sp)
    sp.add_argument("--filters", help="comma list of filters you own (default: all)")
    sp.add_argument("--min-alt", type=float, default=30.0)
    sp.add_argument("--top", type=int, default=5)
    sp.set_defaults(func=cmd_plan)

    se = sub.add_parser("exposure", help="optimal sub-exposure length")
    se.add_argument("--bortle", type=int, default=5, choices=range(1, 10))
    se.add_argument("--sqm", type=float, help="measured SQM overrides --bortle")
    se.add_argument("--sky-rate", type=float, help="measured sky e-/px/s (from 'analyze') overrides sky model")
    se.add_argument("--filter", default="none")
    se.add_argument("--noise-increase", type=float, default=5.0, help="accepted stack-noise penalty %%")
    _rig_args(se)
    se.set_defaults(func=cmd_exposure)

    sa = sub.add_parser("analyze", help="measure FITS/XISF sub-frames")
    sa.add_argument("files", nargs="+")
    sa.add_argument("--gain", type=float, help="e-/ADU (overrides header EGAIN)")
    sa.add_argument("--offset", type=float, help="bias/offset pedestal in ADU")
    sa.add_argument("--exptime", type=float, help="override exposure time, s")
    sa.set_defaults(func=cmd_analyze)

    sub.add_parser("cameras", help="list known cameras").set_defaults(func=cmd_cameras)
    sub.add_parser("filters", help="list known filters").set_defaults(func=cmd_filters)
    sub.add_parser("targets", help="list the target catalog").set_defaults(func=cmd_targets)

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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
