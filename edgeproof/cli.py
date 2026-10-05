"""EdgeProof command line.

    edgeproof device                 what SoC / Hexagon arch is connected
    edgeproof scan app-debug.apk     run the checks against that APK + device
        --soc SM8850 / --arch 81     name the target when no device is attached
    edgeproof parity --launch        prove the NPU gives the host's answer
        --via-app PKG / --logfile F  which app to launch, or a saved log
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, apk as apkmod, report, sdk
from .checks import check_cdsprpc, check_skels
from .parity import check_parity
from .report import FAIL
from .soc import arch_for_soc, connected


def _cmd_device(args: argparse.Namespace) -> int:
    if not sdk.adb_path():
        print("adb not found. Install Android platform-tools or set ANDROID_HOME.")
        return 2
    dev = connected()
    if not dev:
        print("No authorised device. Plug one in, accept the USB-debugging prompt, and retry.")
        return 2
    print(f"Device : {dev.label}")
    print(f"  serial   {dev.serial}")
    print(f"  model    {dev.model}")
    print(f"  soc      {dev.soc or '(unreported)'}")
    print(f"  platform {dev.platform or '(unreported)'}")
    if dev.htp_arch:
        print(f"  hexagon  V{dev.htp_arch}  ->  loads {dev.htp_lib}")
    else:
        print("  hexagon  unknown (SoC not in the arch table) — pass --arch to scan")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    try:
        info = apkmod.inspect(args.apk)
    except FileNotFoundError:
        print(f"APK not found: {args.apk}")
        return 2

    dev = connected()
    arch_override = args.arch or (arch_for_soc(args.soc) if args.soc else None)
    if args.soc and arch_override is None:
        print(f"Unknown SoC '{args.soc}'. Pass --arch <NN> explicitly if you know it.")
        return 2

    if dev and dev.htp_arch:
        target = dev.label + " (connected)"
    elif arch_override:
        target = f"{args.soc or 'arch'} · Hexagon V{arch_override} (named, no device)"
    else:
        target = "no device, no --soc/--arch (arch-dependent checks limited)"

    findings = [
        check_skels(info, dev, args.soc, arch_override),
        check_cdsprpc(info),
    ]

    print(report.header("on-device NPU readiness",
                        target, f"{info.path.name} ({info.size / 1048576:.1f} MB)"))
    for f in findings:
        print(f.render())
        print()
    print(report.summary(findings))
    return 1 if any(f.status == FAIL for f in findings) else 0


def _cmd_parity(args: argparse.Namespace) -> int:
    dev = connected()
    if args.logfile:
        target = f"saved log {args.logfile}"
    elif dev:
        target = f"{dev.label} (connected) · app {args.package}"
    else:
        target = f"no device · app {args.package}"
    f = check_parity(args.package, args.tolerance, args.launch, args.timeout, args.logfile)
    print(report.header("NPU parity (device vs host)", target,
                        args.package if not args.logfile else "-"))
    print(f.render())
    print()
    print(report.summary([f]))
    return 1 if f.status == FAIL else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="edgeproof",
                                description="Ship a model to the NPU, verified.")
    p.add_argument("--version", action="version", version=f"edgeproof {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("device", help="show the connected device's SoC / Hexagon arch")

    s = sub.add_parser("scan", help="run NPU-readiness checks against an APK")
    s.add_argument("apk", help="path to the .apk")
    s.add_argument("--soc", help="target SoC when no device is attached, e.g. SM8850")
    s.add_argument("--arch", type=int, help="target Hexagon arch directly, e.g. 81")

    pp = sub.add_parser("parity", help="prove the NPU gives the same answer as the host")
    pp.add_argument("--via-app", dest="package", default="app.pehredaar",
                    help="app whose launch self-test to read (default app.pehredaar)")
    pp.add_argument("--launch", action="store_true",
                    help="force-stop and relaunch the app to trigger a fresh self-test")
    pp.add_argument("--tolerance", type=float, default=0.03,
                    help="max allowed |device - host| (default 0.03)")
    pp.add_argument("--timeout", type=int, default=40, help="seconds to wait for the self-test")
    pp.add_argument("--logfile", help="parse a saved logcat instead of a live device")

    args = p.parse_args(argv)
    if args.cmd == "device":
        return _cmd_device(args)
    if args.cmd == "scan":
        return _cmd_scan(args)
    if args.cmd == "parity":
        return _cmd_parity(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
