"""Identify the connected device's SoC and its Hexagon HTP architecture.

QNN names its NPU backend libraries by the HTP *architecture* version
(libQnnHtpV<NN>Skel.so), not by SoC — so to know which skel a device actually
loads you first map SoC -> HTP arch. The table below covers Snapdragon flagships;
unknown SoCs are reported honestly rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import sdk

# Snapdragon SoC model -> Hexagon HTP architecture (the "V<NN>" in the skel name).
# Source: the QNN SDK's own per-SoC backend selection.
SOC_TO_HTP: dict[str, int] = {
    "SM8350": 68,   # Snapdragon 888
    "SM8450": 69,   # 8 Gen 1
    "SM8550": 73,   # 8 Gen 2
    "SM7475": 73,
    "SM8650": 75,   # 8 Gen 3
    "SM8750": 79,   # 8 Elite
    "SM8850": 81,   # the iQOO this was built on
}

# Fallback: board/platform codename -> SoC model, when ro.soc.model is absent.
PLATFORM_TO_SOC: dict[str, str] = {
    "lahaina": "SM8350",
    "taro": "SM8450",
    "kalama": "SM8550",
    "pineapple": "SM8650",
    "sun": "SM8750",
}


@dataclass
class Device:
    serial: str
    model: str          # ro.product.model, e.g. "I2501"
    soc: str            # ro.soc.model, e.g. "SM8850" (may be "")
    platform: str       # ro.board.platform codename
    htp_arch: int | None  # 81 => libQnnHtpV81Skel.so; None if unknown

    @property
    def htp_lib(self) -> str | None:
        return f"libQnnHtpV{self.htp_arch}Skel.so" if self.htp_arch else None

    @property
    def label(self) -> str:
        soc = self.soc or self.platform or "unknown SoC"
        arch = f"Hexagon V{self.htp_arch}" if self.htp_arch else "Hexagon arch unknown"
        return f"{self.model} · {soc} · {arch}"


def _getprop(adb: str, serial: str, prop: str) -> str:
    try:
        return sdk.run([adb, "-s", serial, "shell", "getprop", prop], timeout=15).strip()
    except sdk.ToolError:
        return ""


def connected() -> Device | None:
    """The first authorised device, or None. Never raises for a missing device."""
    adb = sdk.adb_path()
    if not adb:
        return None
    try:
        out = sdk.run([adb, "devices"], timeout=15)
    except sdk.ToolError:
        return None
    serial = next((ln.split("\t")[0] for ln in out.splitlines()[1:]
                   if ln.strip() and ln.strip().endswith("device")), None)
    if not serial:
        return None

    model = _getprop(adb, serial, "ro.product.model")
    soc = _getprop(adb, serial, "ro.soc.model")
    platform = _getprop(adb, serial, "ro.board.platform")
    if not soc:
        soc = PLATFORM_TO_SOC.get(platform, "")
    return Device(serial, model, soc, platform, SOC_TO_HTP.get(soc))


def arch_for_soc(soc: str) -> int | None:
    """HTP arch for a SoC string supplied on the command line (--soc SM8850)."""
    return SOC_TO_HTP.get(soc.upper().strip())
