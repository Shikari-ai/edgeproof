"""Inspect an APK without unpacking it: native libraries and manifest facts.

Two things the checks need:
  * which NPU backend libraries are bundled, and how big they are;
  * what the manifest declares (specifically <uses-native-library> entries).

Native libs come straight from the zip central directory. Manifest facts come
from aapt when it is available, with a raw-bytes fallback so the tool still
works on a machine with only platform-tools installed.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import sdk

# libQnnHtpV81Skel.so / libQnnDspV66Skel.so -> ("Htp", 81) / ("Dsp", 66)
_SKEL = re.compile(r"libQnn(Htp|Dsp)V(\d+)Skel\.so$")


@dataclass
class NativeLib:
    name: str          # bare file name
    size: int          # uncompressed bytes
    family: str | None  # "Htp" or "Dsp" for a backend skel, else None
    arch: int | None    # the V<NN> number for a skel, else None


@dataclass
class ApkInfo:
    path: Path
    size: int
    libs: list[NativeLib] = field(default_factory=list)
    uses_native_libs: list[str] = field(default_factory=list)
    manifest_source: str = "unknown"   # "aapt", "aapt2", "raw-bytes"

    @property
    def skels(self) -> list[NativeLib]:
        return [l for l in self.libs if l.family]

    def has(self, substr: str) -> bool:
        return any(substr.lower() in l.name.lower() for l in self.libs)

    @property
    def uses_qnn(self) -> bool:
        """True when the app bundles the QNN HTP backend (so it drives the DSP)."""
        return self.has("libQnnHtp") or self.has("libQnnSystem")


def _native_libs(zf: zipfile.ZipFile) -> list[NativeLib]:
    out = []
    for info in zf.infolist():
        if not info.filename.endswith(".so"):
            continue
        name = info.filename.rsplit("/", 1)[-1]
        m = _SKEL.search(name)
        fam, arch = (m.group(1), int(m.group(2))) if m else (None, None)
        out.append(NativeLib(name, info.file_size, fam, arch))
    return out


def _uses_native_libs_aapt(path: Path) -> tuple[list[str], str] | None:
    found = sdk.aapt_path()
    if not found:
        return None
    tool, is_v2 = found
    cmd = ([tool, "dump", "xmltree", "--file", "AndroidManifest.xml", str(path)]
           if is_v2 else [tool, "dump", "xmltree", str(path), "AndroidManifest.xml"])
    try:
        tree = sdk.run(cmd, timeout=30)
    except sdk.ToolError:
        return None
    names, in_elem = [], False
    for ln in tree.splitlines():
        s = ln.strip()
        if s.startswith("E:"):
            in_elem = "uses-native-library" in s
        elif in_elem and "android:name" in s:
            m = re.search(r'="([^"]+)"', s)
            if m:
                names.append(m.group(1))
    return names, ("aapt2" if is_v2 else "aapt")


def _uses_native_libs_raw(zf: zipfile.ZipFile) -> tuple[list[str], str]:
    """Fallback: scan the binary manifest for known vendor-library strings.

    Binary AXML keeps string literals in a pool; search both UTF-8 and UTF-16LE
    encodings. Heuristic, but enough to tell whether a declaration is present.
    """
    try:
        blob = zf.read("AndroidManifest.xml")
    except KeyError:
        return [], "raw-bytes"
    names = []
    for cand in ("libcdsprpc.so", "libvndksupport.so", "libOpenCL.so"):
        if cand.encode("utf-8") in blob or cand.encode("utf-16-le") in blob:
            names.append(cand)
    return names, "raw-bytes"


def inspect(path: str | Path) -> ApkInfo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = ApkInfo(path=path, size=path.stat().st_size)
    with zipfile.ZipFile(path) as zf:
        info.libs = _native_libs(zf)
        viaapt = _uses_native_libs_aapt(path)
        if viaapt is not None:
            info.uses_native_libs, info.manifest_source = viaapt
        else:
            info.uses_native_libs, info.manifest_source = _uses_native_libs_raw(zf)
    return info
