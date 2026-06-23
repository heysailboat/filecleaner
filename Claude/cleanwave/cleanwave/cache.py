"""
cache.py — serialize/deserialize dry-run results so real runs can skip
the scan + AI pass entirely.

cache file lives at ~/.cleanwave/cache_<stamp>.json
freshness window: 2 hours (configurable via CLEANWAVE_CACHE_TTL_HOURS env var)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from .models import FileInfo, FileDecision, Destination

_TTL = float(os.environ.get("CLEANWAVE_CACHE_TTL_HOURS", "2")) * 3600
_CACHE_DIR = Path.home() / ".cleanwave"


def _decision_to_dict(fi: FileInfo, dec: FileDecision) -> dict:
    return {
        "path":        str(fi.path),
        "size":        fi.size,
        "mtime":       fi.mtime,
        "atime":       fi.atime,
        "ext":         fi.ext,
        "destination": dec.destination.value,
        "category":    dec.category,
        "subcategory": dec.subcategory,
        "reason":      dec.reason,
        "confidence":  dec.confidence,
        "new_name":    dec.new_name,
    }


def _dict_to_pair(d: dict) -> tuple[FileInfo, FileDecision]:
    fi = FileInfo(
        path=Path(d["path"]),
        size=d["size"],
        mtime=d["mtime"],
        atime=d["atime"],
        ext=d["ext"],
    )
    dec = FileDecision(
        destination=Destination(d["destination"]),
        category=d["category"],
        subcategory=d.get("subcategory", ""),
        reason=d["reason"],
        confidence=d.get("confidence", 1.0),
        new_name=d.get("new_name"),
    )
    return fi, dec


def save(
    actionable: list[tuple[FileInfo, FileDecision]],
    scan_dirs: list[str],
) -> Path:
    """Write a cache file after a dry-run. Returns path to the file."""
    _CACHE_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = _CACHE_DIR / f"cache_{stamp}.json"

    payload = {
        "created_at": time.time(),
        "scan_dirs":  scan_dirs,
        "items":      [_decision_to_dict(fi, dec) for fi, dec in actionable],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_fresh(scan_dirs: list[str]) -> Optional[tuple[list, float]]:
    """
    Find the most recent cache file that matches scan_dirs and is within TTL.
    Returns (actionable_list, created_at) or None if nothing usable found.
    """
    if not _CACHE_DIR.exists():
        return None

    candidates = sorted(_CACHE_DIR.glob("cache_*.json"), reverse=True)
    now = time.time()

    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        created_at = data.get("created_at", 0)
        if now - created_at > _TTL:
            continue  # stale

        if sorted(data.get("scan_dirs", [])) != sorted(scan_dirs):
            continue  # different scope

        items = [_dict_to_pair(d) for d in data.get("items", [])]
        return items, created_at

    return None


def clear(scan_dirs: list[str]) -> int:
    """Delete all cache files matching scan_dirs. Returns count deleted."""
    if not _CACHE_DIR.exists():
        return 0
    deleted = 0
    for path in _CACHE_DIR.glob("cache_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if sorted(data.get("scan_dirs", [])) == sorted(scan_dirs):
                path.unlink()
                deleted += 1
        except Exception:
            pass
    return deleted
