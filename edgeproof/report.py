"""Findings and how they print. One Finding per check; a small coloured report."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

_COLOR = {PASS: "32", WARN: "33", FAIL: "31", INFO: "36"}


def _tty() -> bool:
    return sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


@dataclass
class Finding:
    status: str          # PASS / WARN / FAIL / INFO
    title: str
    detail: list[str] = field(default_factory=list)   # body lines
    fix: list[str] = field(default_factory=list)       # how to fix
    note: str | None = None                            # honest caveat

    def render(self) -> str:
        tag = _c(f"[{self.status}]", _COLOR.get(self.status, "0"))
        lines = [f"{tag} {_c(self.title, '1')}"]
        lines += [f"    {d}" for d in self.detail]
        if self.fix:
            lines.append(f"    {_c('fix:', '1')}")
            lines += [f"      {f}" for f in self.fix]
        if self.note:
            lines.append(f"    {_c('note:', '2')} {self.note}")
        return "\n".join(lines)


def header(title: str, target: str, apk: str) -> str:
    bar = _c("EdgeProof", "1;36")
    return f"{bar} — {title}\n  target: {target}\n  apk:    {apk}\n"


def summary(findings: list[Finding]) -> str:
    n = {s: sum(f.status == s for f in findings) for s in (PASS, WARN, FAIL)}
    parts = [_c(f"{n[PASS]} pass", "32"), _c(f"{n[WARN]} warn", "33"),
             _c(f"{n[FAIL]} fail", "31")]
    return "  " + "  ·  ".join(parts)
