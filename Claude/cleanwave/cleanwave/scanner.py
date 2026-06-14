"""
scanner.py — walk directories, detect and skip OS/app/venv dirs, collect FileInfo
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .models import FileInfo, SkippedDir, ScanResult

# ── OS / system directories ──────────────────────────────────────────────────

_MACOS_SYSTEM = {
    "/System", "/Library", "/Applications",
    "/usr", "/bin", "/sbin", "/private",
    "/Volumes", "/Network", "/cores", "/dev",
    "/etc", "/var", "/opt", "/tmp",
}

_MACOS_APP_DATA = {
    "Library/Application Support",
    "Library/Frameworks",
    "Library/PreferencePanes",
    "Library/Preferences",
    "Library/PrivateFrameworks",
    "Library/Safari",
    "Library/Mail",
}

_WINDOWS_SYSTEM = {
    "Windows", "Program Files", "Program Files (x86)",
    "ProgramData", "Recovery", "PerfLogs",
    "System Volume Information", "$Recycle.Bin", "$WinREAgent",
}

_WINDOWS_APP_DATA = {
    "AppData\\Roaming",
    "AppData\\Local\\Microsoft",
    "AppData\\Local\\Packages",
}

# ── Virtual env / tooling dirs — skipped everywhere, by name ────────────────

_VENV_NAMES = {
    ".venv", "venv", "env",
    "node_modules", "__pycache__",
    ".git", ".hg", ".svn",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".eggs",
    ".next", ".nuxt", ".svelte-kit",
    ".parcel-cache", ".turbo",
}


def _is_path_under(child: Path, parent_str: str) -> bool:
    """Python 3.8-safe replacement for Path.is_relative_to()."""
    try:
        child.resolve().relative_to(Path(parent_str).resolve())
        return True
    except ValueError:
        return False


def _get_atime(path: Path, stat_result) -> float:
    """
    Best-effort last-accessed time.
    On macOS, st_atime is often stale/disabled — use Spotlight instead.
    Falls back to st_atime on failure or on Windows.
    """
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["mdls", "-name", "kMDItemLastUsedDate", "-raw", str(path)],
                capture_output=True, text=True, timeout=2,
            )
            raw = result.stdout.strip()
            if raw and raw != "(null)":
                # format: "2024-03-15 14:22:10 +0000"
                from datetime import datetime, timezone
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
                return dt.replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            pass
    return stat_result.st_atime


def _classify_dir(path: Path) -> tuple[bool, str]:
    """Returns (should_skip, reason)."""
    name = path.name

    # venv / tooling — cheapest check first
    if name in _VENV_NAMES or name.endswith(".egg-info"):
        return True, "virtualenv"

    path_str = str(path.resolve())

    if sys.platform == "darwin":
        for d in _MACOS_SYSTEM:
            if path_str == d or path_str.startswith(d + "/"):
                return True, "os_system"
        home = str(Path.home())
        for d in _MACOS_APP_DATA:
            if _is_path_under(path, f"{home}/{d}"):
                return True, "app_data"

    elif sys.platform == "win32":
        drive = Path(path).drive + "\\"
        for d in _WINDOWS_SYSTEM:
            candidate = os.path.join(drive, d)
            if path_str.lower().startswith(candidate.lower()):
                return True, "os_system"
        home = str(Path.home())
        for d in _WINDOWS_APP_DATA:
            if _is_path_under(path, f"{home}\\{d}"):
                return True, "app_data"

    return False, ""


def collect_files(
    scan_dirs: list[str],
    skip_hidden: bool = False,
    max_file_size_mb: int = 0,
) -> ScanResult:
    """
    Walk scan_dirs recursively, skipping OS/app/venv directories.
    Returns collected FileInfo list + skipped dirs log.
    """
    result = ScanResult()
    seen_paths: set[str] = set()
    max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb else 0

    for root_dir in scan_dirs:
        start = Path(root_dir).expanduser().resolve()
        if not start.exists():
            continue

        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            current = Path(dirpath)

            filtered = []
            for d in dirnames:
                sub = current / d
                if skip_hidden and d.startswith("."):
                    continue
                skip, reason = _classify_dir(sub)
                if skip:
                    result.skipped_dirs.append(SkippedDir(path=sub, reason=reason))
                else:
                    filtered.append(d)
            dirnames[:] = filtered

            for fname in filenames:
                if skip_hidden and fname.startswith("."):
                    continue

                fpath = current / fname
                abs_str = str(fpath.resolve())

                if abs_str in seen_paths:
                    continue
                seen_paths.add(abs_str)

                try:
                    stat = fpath.stat()
                except (OSError, PermissionError):
                    result.skipped_dirs.append(
                        SkippedDir(path=fpath, reason="permission_denied")
                    )
                    continue

                if max_bytes and stat.st_size > max_bytes:
                    continue

                result.files.append(FileInfo(
                    path=fpath,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    atime=_get_atime(fpath, stat),
                    ext=fpath.suffix.lower(),
                ))

    return result
