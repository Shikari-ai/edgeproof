"""The checks. Each takes inspected facts and returns one Finding.

Wired so far:
  * skels    — SoC-aware NPU backend stripper (unused Hexagon skels are dead weight)
  * cdsprpc  — the undeclared vendor library that stops QNN reaching the DSP
"""

from __future__ import annotations

from .apk import ApkInfo
from .report import FAIL, INFO, PASS, WARN, Finding
from .soc import Device


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


def check_skels(apk: ApkInfo, device: Device | None, soc_override: str | None,
                arch_override: int | None) -> Finding:
    """Only the skel matching the device's Hexagon arch ever loads; the rest are
    bundled weight. On a single-target build they can be stripped."""
    skels = [l for l in apk.skels]
    if not skels:
        return Finding(INFO, "No NPU backend libraries bundled",
                       ["This APK ships no libQnnHtpV*/DspV* skels — nothing to strip."])

    arch = arch_override or (device.htp_arch if device else None)
    source = ("--soc" if arch_override and soc_override else
              f"device {device.label}" if device and device.htp_arch else None)
    if arch is None:
        listed = [f"{l.name:28} {_mb(l.size)}" for l in sorted(skels, key=lambda l: -l.size)]
        return Finding(WARN, "Bundled NPU skels found, but target arch unknown",
                       ["Could not determine the device's Hexagon architecture, so"
                        " cannot say which skel is the live one:", *["  " + s for s in listed]],
                       ["Connect the target device, or pass --soc SM8850 (or --arch 81)."])

    target = f"libQnnHtpV{arch}Skel.so"
    present = {l.name: l for l in skels}
    keep = present.get(target)
    unused = [l for l in skels if l.name != target]
    saved = sum(l.size for l in unused)

    if keep is None:
        return Finding(FAIL, f"Required skel for this device is missing (V{arch})",
                       [f"The device runs Hexagon V{arch}, which needs {target},",
                        "but that skel is not in the APK — the model cannot run on the",
                        "NPU here and will fall back to CPU (or fail).",
                        f"Bundled instead: {', '.join(l.name for l in skels)}"],
                       [f"Add the V{arch} QNN backend to the build (match your QNN SDK"
                        " version to the device arch)."])

    if not unused:
        return Finding(PASS, f"Only the needed NPU skel is bundled (V{arch})",
                       [f"{target} ({_mb(keep.size)}) is present and is the one this device loads."])

    listed = [f"{l.name:28} {_mb(l.size)}" for l in sorted(unused, key=lambda l: -l.size)]
    excludes = "\n".join(f'        exclude "**/{l.name}"' for l in unused)
    detail = [f"This device uses Hexagon V{arch} → {target} ({_mb(keep.size)})."
              + (f"  [{source}]" if source else ""),
              f"{len(unused)} other-arch skels are bundled but never load on this SoC:",
              *["  " + s for s in listed],
              f"Removable on a single-target build: {_mb(saved)}."]
    fix = ["android/app/build.gradle — packagingOptions { jniLibs {",
           *excludes.splitlines(),
           "    } }"]
    return Finding(WARN, f"Unused NPU skel libraries — {_mb(saved)} removable",
                   detail, fix,
                   note="Stripping ties the APK to this Hexagon arch; keep others only"
                        " if you ship one build across SoC generations.")


def check_cdsprpc(apk: ApkInfo) -> Finding:
    """Since Android 12 an app must declare the vendor libraries it dlopens. QNN
    reaches the DSP through libcdsprpc.so; undeclared, HTP init fails."""
    if not apk.uses_qnn:
        return Finding(INFO, "No QNN HTP backend bundled",
                       ["libcdsprpc.so is only needed to reach the Hexagon DSP via QNN;"
                        " this APK does not bundle it."])

    declared = any(n.lower() == "libcdsprpc.so" for n in apk.uses_native_libs)
    heuristic = apk.manifest_source == "raw-bytes"

    if declared:
        f = Finding(PASS, "DSP vendor library is declared",
                    ["APK bundles the QNN HTP backend, so it needs libcdsprpc.so to reach"
                     " the DSP.",
                     "Manifest declares: <uses-native-library android:name=\"libcdsprpc.so\"> ✓"])
    else:
        f = Finding(FAIL, "QNN HTP bundled, but libcdsprpc.so is NOT declared",
                    ["Since Android 12 an app can't dlopen a vendor library it hasn't",
                     "declared. QNN loads the DSP through libcdsprpc.so, so without the",
                     "declaration HTP init fails with QNN_DEVICE_ERROR_INVALID_CONFIG and",
                     "the model silently never reaches the NPU."],
                    ["AndroidManifest.xml, inside <application>:",
                     '  <uses-native-library android:name="libcdsprpc.so"',
                     '                        android:required="false" />'])
    if heuristic:
        f.note = ("manifest read via raw-bytes fallback (aapt not found) — install"
                  " Android build-tools for an exact read.")
    elif declared:
        f.note = 'set android:required="false" so installs on non-Qualcomm devices still succeed.'
    return f
