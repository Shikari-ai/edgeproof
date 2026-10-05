"""Parity check: did the model give the SAME answer on the NPU as on the host?

Running on the NPU is worth nothing if fp16 / quantisation moved the answer. The
honest proof is a fixed set of inputs scored both ways and the worst difference
reported. EdgeProof reads that proof off a self-test the app prints at launch:

    selftest NPU encoder · CPU front end + heads: max |Δrisk| 0.016 over 10 windows · pattern 8/8
    selftest[0] phone 0.7483 laptop 0.7517  demo_scam_otp / en-US-...

Any app can emit a line in that shape; Pehredaar already does. EdgeProof launches
the app (or reads a saved log), parses the drift, execution provider and pattern
agreement, and PASS/FAILs against a tolerance.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import sdk
from .report import FAIL, INFO, PASS, WARN, Finding
from .soc import connected

# "selftest <provider>: max |Δrisk| 0.016 over 10 windows · pattern 8/8"
_SUMMARY = re.compile(
    r"selftest\s+(?P<prov>.+?):\s*max.*?(?P<drift>\d+\.\d+)\s+over\s+(?P<n>\d+)\s+windows"
    r".*?pattern\s+(?P<ok>\d+)\s*/\s*(?P<tot>\d+)")
# "selftest[0] phone 0.7483 laptop 0.7517  <clip> / <voice>"
_WINDOW = re.compile(
    r"selftest\[(?P<i>\d+)\]\s+phone\s+(?P<phone>[\d.]+)\s+laptop\s+(?P<laptop>[\d.]+)\s*(?P<label>.*)")


@dataclass
class ParityResult:
    provider: str
    drift: float
    windows: int
    ok: int
    total: int
    worst: tuple[str, float] | None = None   # (label, |phone-laptop|)
    pairs: int = 0                            # how many per-window lines were seen

    @property
    def on_npu(self) -> bool:
        return "npu" in self.provider.lower()

    @property
    def pattern_full(self) -> bool:
        return self.total > 0 and self.ok == self.total


def parse(text: str) -> ParityResult | None:
    """Pull the last self-test out of a block of logcat (or a saved log)."""
    worst_label, worst_d = None, -1.0
    pairs = 0
    for m in _WINDOW.finditer(text):
        pairs += 1
        d = abs(float(m["phone"]) - float(m["laptop"]))
        if d > worst_d:
            worst_d, worst_label = d, (m["label"].strip() or f"window {m['i']}")
    # last summary wins (a fresh launch appends a new one)
    summ = None
    for summ in _SUMMARY.finditer(text):
        pass
    if not summ:
        return None
    return ParityResult(
        provider=summ["prov"].strip(),
        drift=float(summ["drift"]),
        windows=int(summ["n"]),
        ok=int(summ["ok"]),
        total=int(summ["tot"]),
        worst=(worst_label, worst_d) if worst_label else None,
        pairs=pairs,
    )


def _collect_from_device(package: str, launch: bool, timeout: int) -> tuple[str, str | None]:
    """Return (logtext, error). Launches the app if asked, then polls logcat."""
    adb = sdk.adb_path()
    if not adb:
        return "", "adb not found (install platform-tools or set ANDROID_HOME)."
    dev = connected()
    if not dev:
        return "", "no authorised device connected."
    base = [adb, "-s", dev.serial]
    if launch:
        sdk.run(base + ["logcat", "-c"], timeout=15)
        sdk.run(base + ["shell", "am", "force-stop", package], timeout=15)
        sdk.run(base + ["shell", "monkey", "-p", package, "-c",
                        "android.intent.category.LAUNCHER", "1"], timeout=20)
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        text = sdk.run(base + ["logcat", "-d", "-t", "4000"], timeout=20)
        if _SUMMARY.search(text):
            return text, None
        time.sleep(2)
    return text, (f"no parity self-test seen within {timeout}s"
                  + ("" if launch else " (try --launch to trigger it)."))


def check_parity(package: str, tolerance: float, launch: bool, timeout: int,
                 logfile: str | None) -> Finding:
    if logfile:
        try:
            text = open(logfile, encoding="utf-8", errors="replace").read()
        except OSError as e:
            return Finding(FAIL, "Parity log not readable", [str(e)])
        err = None
    else:
        text, err = _collect_from_device(package, launch, timeout)

    if err and not text:
        return Finding(INFO, "Parity not checked", [err])

    r = parse(text)
    if r is None:
        return Finding(FAIL, "No parity self-test found",
                       ["EdgeProof could not find a self-test line in the log.",
                        "Expected something like:",
                        "  selftest NPU encoder ...: max |Δrisk| 0.016 over 10 windows · pattern 8/8"],
                       [f"Make the app emit it at launch, then: edgeproof parity --via-app {package} --launch"])

    detail = [f"provider : {r.provider}",
              f"max drift: {r.drift:.4f}   (tolerance {tolerance:.4f})",
              f"windows  : {r.windows}   pattern agreement {r.ok}/{r.total}"]
    if r.worst:
        detail.append(f"worst    : {r.worst[1]:.4f} on {r.worst[0]}")

    if not r.on_npu:
        return Finding(WARN, "Parity ran, but not on the NPU", detail,
                       ["The self-test provider does not mention the NPU — it may have",
                        "fallen back to CPU. Confirm the QNN EP is actually selected."])
    if r.drift > tolerance:
        return Finding(FAIL, f"NPU answers drift past tolerance ({r.drift:.4f} > {tolerance:.4f})",
                       detail,
                       ["fp16/quant on the NPU moved the answer. Split the graph so the",
                        "sensitive ops stay fp32 on CPU, or raise precision on those nodes,",
                        "then re-run parity."])
    if not r.pattern_full:
        return Finding(WARN, f"Risk matches, but pattern labels disagree ({r.ok}/{r.total})",
                       detail, ["Scores are within tolerance; the secondary pattern head differs."])
    return Finding(PASS, f"NPU matches the host (drift {r.drift:.4f} ≤ {tolerance:.4f})",
                   detail + [f"{r.ok}/{r.total} patterns agree; running on the NPU and correct."])
