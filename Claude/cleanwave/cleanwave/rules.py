"""
rules.py — rule-based file classification
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from .models import FileInfo, FileDecision, Destination

JUNK_EXTENSIONS = {
    ".tmp", ".temp", ".cache", ".cached", ".bak", ".old",
    ".swp", ".swo", ".part", ".crdownload", ".download", ".dmp",
}

LOG_EXTENSIONS = {".log", ".log1", ".log2"}

INSTALLER_EXTENSIONS = {
    ".dmg", ".pkg",
    ".exe", ".msi", ".cab",
    ".deb", ".rpm", ".appimage",
}

# never flag these regardless of age — system/app resource types
_PROTECTED_EXTENSIONS = {
    ".saver",    # macOS screen savers
    ".kext",     # kernel extensions
    ".plugin",   # plugins
    ".bundle",   # app bundles
    ".framework",
    ".app",
    ".prefpane",
    ".qlgenerator",
    ".mdimporter",
}

JUNK_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".localized",
    ".spotlight-v100", ".trashes", ".fseventsd",
    "hiberfil.sys", "pagefile.sys", "swapfile.sys",
}

_EXT_SUBCATEGORY: dict[str, set[str]] = {
    "images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic",
                  ".webp", ".raw", ".cr2", ".nef", ".arw", ".svg"},
    "documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".txt", ".md", ".pages", ".numbers", ".keynote", ".rtf", ".odt"},
    "archives":  {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz",
                  ".dmg", ".pkg", ".iso"},
    "media":     {".mp4", ".mov", ".avi", ".mkv", ".mp3", ".flac", ".wav",
                  ".aac", ".m4a", ".m4v", ".wmv", ".ogg", ".opus"},
    "code":      {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp",
                  ".h", ".rb", ".go", ".rs", ".php", ".swift", ".kt", ".cs",
                  ".sh", ".bash", ".zsh", ".fish"},
}


def _ext_subcategory(ext: str) -> str:
    for subcat, exts in _EXT_SUBCATEGORY.items():
        if ext in exts:
            return subcat
    return "other"


_VAGUE_PATTERNS = [
    r"^untitled(\s*\d+)?$",
    r"^screenshot(\s*\d+)?$",
    r"^screen\s*shot",
    r"^image\s*\d+$",
    r"^img\s*\d+$",
    r"^file\s*\d+$",
    r"^new\s+(folder|document|text file)",
    r"^document\s*\d*$",
    r"^copy of ",
    r"^\d{4,}$",
    r"^[a-f0-9]{8,}$",
    r"^dsc\d+$",
    r"^img_\d+$",
    r"^photo_\d+$",
    r"^clip\d+$",
    r"^recording\s*\d+$",
    r"^voice\s*(memo\s*)?\d+$",
    r"^scan\d+$",
    r"^download(\s*\d+)?$",
    r"^attachment.*$",
]
_VAGUE_RE = [re.compile(p, re.IGNORECASE) for p in _VAGUE_PATTERNS]


def _is_vague_name(path: Path) -> bool:
    stem = path.stem.strip()
    return any(rx.match(stem) for rx in _VAGUE_RE)


_IMPORTANT_PATTERNS = [
    r"recovery", r"password", r"passphrase", r"secret", r"private",
    r"credential", r"license", r"serial", r"key", r"token",
    r"ssh", r"gpg", r"certificate", r"backup", r"2fa",
]
_IMPORTANT_EXTENSIONS = {".key", ".pem", ".p12", ".pfx", ".kdbx", ".asc"}
_IMPORTANT_RE = [re.compile(p, re.IGNORECASE) for p in _IMPORTANT_PATTERNS]


def is_whitelisted(path: Path, extra_patterns: list[str] = ()) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in _IMPORTANT_EXTENSIONS:
        return True
    for rx in _IMPORTANT_RE:
        if rx.search(name):
            return True
    for pat in extra_patterns:
        import fnmatch
        if fnmatch.fnmatch(name, pat.lower()):
            return True
    return False


def classify(
    fi: FileInfo,
    old_threshold_days: int = 365,
    installer_grace_days: int = 14,
    extra_whitelist: list[str] = (),
    since_timestamp: Optional[float] = None,
) -> FileDecision:
    """
    Classify a single file via rules.
    since_timestamp: if set, any file with last_activity before this epoch
    is flagged as old_file regardless of old_threshold_days.
    """
    name_lower = fi.path.name.lower()
    last_activity = max(fi.mtime, fi.atime)
    age_days = (time.time() - last_activity) / 86400

    # 1. whitelist
    if is_whitelisted(fi.path, extra_whitelist):
        return FileDecision(
            destination=Destination.KEEP,
            category="keep",
            reason="matches important-file pattern",
        )

    # 2. protected extensions — never flag regardless of age
    if fi.ext in _PROTECTED_EXTENSIONS:
        return FileDecision(
            destination=Destination.KEEP,
            category="keep",
            reason=f"protected file type ({fi.ext})",
        )

    # 3. empty
    if fi.size == 0:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk", subcategory="temp",
            reason="empty file (0 bytes)",
        )

    # 4. junk names
    if name_lower in JUNK_NAMES:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk", subcategory="system",
            reason=f"system-generated junk ({fi.path.name})",
        )

    # 5. junk extensions
    if fi.ext in JUNK_EXTENSIONS:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk", subcategory="temp",
            reason=f"temporary/junk file type ({fi.ext})",
            confidence=0.95,
        )

    # 6. old logs
    if fi.ext in LOG_EXTENSIONS and age_days > 7:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk", subcategory="logs",
            reason=f"log file, no activity in {age_days:.0f} days",
            confidence=0.90,
        )

    # 7. old installers
    if fi.ext in INSTALLER_EXTENSIONS and age_days > installer_grace_days:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk", subcategory="installers",
            reason=f"installer, no activity in {age_days:.0f} days",
            confidence=0.85,
        )

    # 8. --since cutoff (takes priority over threshold check)
    if since_timestamp is not None and last_activity < since_timestamp:
        return FileDecision(
            destination=Destination.OLD_FILES,
            category="old_file",
            subcategory=_ext_subcategory(fi.ext),
            reason=f"no activity since cutoff date (last: {age_days:.0f} days ago)",
            confidence=0.80,
        )

    # 9. old files by threshold
    if age_days > old_threshold_days:
        return FileDecision(
            destination=Destination.OLD_FILES,
            category="old_file",
            subcategory=_ext_subcategory(fi.ext),
            reason=f"no activity in {age_days:.0f} days (threshold: {old_threshold_days})",
            confidence=0.80,
        )

    # 10. vague name
    if _is_vague_name(fi.path):
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="vague",
            subcategory=_ext_subcategory(fi.ext),
            reason="generic/untitled filename",
            confidence=0.50,
        )

    return FileDecision(
        destination=Destination.KEEP,
        category="keep",
        reason="no cleanup rule matched",
    )
