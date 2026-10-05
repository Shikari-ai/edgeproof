"""Locate and run the Android SDK tools EdgeProof leans on (adb, aapt/aapt2).

Kept deliberately small: find the binary, run it, hand back stdout. Nothing here
talks about NPUs — that lives in the checks. These helpers just make the SDK
reachable on a machine where it was installed by Android Studio.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class ToolError(RuntimeError):
    """A required SDK tool is missing or returned non-zero."""


def _sdk_root() -> Path | None:
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(env)
        if v and Path(v).is_dir():
            return Path(v)
    # Default Android Studio install locations.
    candidates = [
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",   # Windows
        Path.home() / "Library" / "Android" / "sdk",             # macOS
        Path.home() / "Android" / "Sdk",                         # Linux
    ]
    return next((c for c in candidates if c.is_dir()), None)


def _find(tool: str, *subdirs: str) -> str | None:
    """Return a path to `tool`, searching PATH first, then the SDK subdirs."""
    exe = tool + (".exe" if os.name == "nt" else "")
    on_path = shutil.which(tool) or shutil.which(exe)
    if on_path:
        return on_path
    root = _sdk_root()
    if not root:
        return None
    for sub in subdirs:
        hit = root / sub / exe
        if hit.exists():
            return str(hit)
    return None


def adb_path() -> str | None:
    return _find("adb", "platform-tools")


def aapt_path() -> tuple[str, bool] | None:
    """Return (path, is_aapt2). Prefer classic aapt; fall back to aapt2.

    build-tools holds many versions; pick the highest so newer APKs parse.
    """
    root = _sdk_root()
    bts: list[Path] = []
    if root and (root / "build-tools").is_dir():
        bts = sorted((root / "build-tools").iterdir(), reverse=True)
    for name, is_v2 in (("aapt", False), ("aapt2", True)):
        exe = name + (".exe" if os.name == "nt" else "")
        for bt in bts:
            hit = bt / exe
            if hit.exists():
                return str(hit), is_v2
        on_path = shutil.which(name)
        if on_path:
            return on_path, is_v2
    return None


def run(cmd: list[str], timeout: int = 60) -> str:
    """Run a command, return stdout (text). Raise ToolError on failure."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        raise ToolError(f"not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"timed out: {' '.join(cmd)}") from e
    if p.returncode != 0:
        raise ToolError((p.stderr or p.stdout or "non-zero exit").strip())
    return p.stdout
