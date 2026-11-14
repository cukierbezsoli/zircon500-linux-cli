"""Local profile persistence for Genesis Zircon 500 settings.

The Zircon 500 HID firmware exposes only active stage/count/battery via ``cmd 0x20``
and has no read-back command for stored per-stage DPI values, polling rate, LOD,
debounce, or power settings. Saving applied settings locally mirrors the OEM
software's ``.psf`` profile storage so restarts preserve user edits.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .protocol import DEFAULT_DPI_STAGES


def _profile_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "zircon500" / "profile.json"


def default_profile() -> dict[str, Any]:
    """Return factory-default configurable settings for the UI."""
    return {
        "dpi_stages": [str(v) for v in DEFAULT_DPI_STAGES],
        "dpi_count": 6,
        "active_dpi": 2,
        "dpi_snap": True,
        "polling_rate": 1000,
        "lod": 2,
        "debounce_ms": 2,
        "sleep_minutes": 5,
        "motion_wake": False,
    }


def load_profile() -> dict[str, Any]:
    """Load saved profile merged over defaults; ignore corrupt data cleanly."""
    profile = default_profile()
    try:
        path = _profile_path()
        if not path.is_file():
            return profile
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return profile
    except (OSError, ValueError):
        return profile

    stages = raw.get("dpi_stages")
    if isinstance(stages, list) and len(stages) == 8 and all(isinstance(x, (str, int)) for x in stages):
        profile["dpi_stages"] = [str(x).strip() or profile["dpi_stages"][i] for i, x in enumerate(stages)]

    count = raw.get("dpi_count")
    if isinstance(count, int) and 1 <= count <= 8:
        profile["dpi_count"] = count

    active = raw.get("active_dpi")
    if isinstance(active, int) and 0 <= active <= 7:
        profile["active_dpi"] = min(active, profile["dpi_count"] - 1)

    if isinstance(raw.get("dpi_snap"), bool):
        profile["dpi_snap"] = raw["dpi_snap"]

    rate = raw.get("polling_rate")
    if isinstance(rate, int) and rate in (125, 250, 500, 1000):
        profile["polling_rate"] = rate

    lod = raw.get("lod")
    if isinstance(lod, int) and lod in (1, 2):
        profile["lod"] = lod

    deb = raw.get("debounce_ms")
    if isinstance(deb, int) and 2 <= deb <= 20:
        profile["debounce_ms"] = deb

    sleep_min = raw.get("sleep_minutes")
    if isinstance(sleep_min, int) and 1 <= sleep_min <= 60:
        profile["sleep_minutes"] = sleep_min

    if isinstance(raw.get("motion_wake"), bool):
        profile["motion_wake"] = raw["motion_wake"]

    return profile


def save_profile(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the saved local profile on disk."""
    merged = load_profile()
    merged.update(updates)
    # Re-validate via normalizer rules in memory before writing.
    try:
        path = _profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return merged


def reset_profile() -> dict[str, Any]:
    """Restore local profile to factory defaults."""
    defaults = default_profile()
    try:
        path = _profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return defaults
