"""
rules.py — fast, AI-free classification of files by type and metadata
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .models import FileInfo, FileDecision, Destination

# ── Extension sets ───────────────────────────────────────────────────────────

JUNK_EXTENSIONS = {
    ".tmp", ".temp", ".cache", ".cached", ".bak", ".old",
    ".swp", ".swo", ".part", ".crdownload", ".download",
    ".dmp",  # crash dumps
}

LOG_EXTENSIONS = {".log", ".log1", ".log2"}

INSTALLER_EXTENSIONS = {
    ".dmg", ".pkg",          # macOS
    ".exe", ".msi", ".cab",  # Windows
    ".deb", ".rpm", ".appimage",
}

# Names that are definitely system-generated junk
JUNK_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".localized",
    ".spotlight-v100", ".trashes", ".fseventsd",
    "hiberfil.sys", "pagefile.sys", "swapfile.sys",
}

# ── Vague / generic name patterns ────────────────────────────────────────────
# Files matching these will be queued for AI assessment.

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
    r"^\d{4,}$",            # long purely-numeric name
    r"^[a-f0-9]{8,}$",     # hex hash-like name (temp exports etc.)
    r"^dsc\d+$",            # old camera naming
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


# ── Whitelist check ──────────────────────────────────────────────────────────

_IMPORTANT_PATTERNS = [
    r"recovery",
    r"password",
    r"passphrase",
    r"secret",
    r"private",
    r"credential",
    r"license",
    r"serial",
    r"key",
    r"token",
    r"ssh",
    r"gpg",
    r"certificate",
    r"backup",
    r"2fa",
]
_IMPORTANT_EXTENSIONS = {
    ".key", ".pem", ".p12", ".pfx", ".kdbx", ".asc",
}
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


# ── Main classifier ──────────────────────────────────────────────────────────

def classify(
    fi: FileInfo,
    old_threshold_days: int = 365,
    installer_grace_days: int = 14,
    extra_whitelist: list[str] = (),
) -> FileDecision:
    """
    Apply fast rules to a single file.
    Returns a FileDecision; decision.needs_ai=True means queue for AI pass.
    AI is never the final word — it only informs the 'vague' category.
    """
    name_lower = fi.path.name.lower()
    age_days = (time.time() - fi.mtime) / 86400

    # 1. Whitelist — always keep, no questions
    if is_whitelisted(fi.path, extra_whitelist):
        return FileDecision(
            destination=Destination.KEEP,
            category="keep",
            reason="matches important-file pattern",
        )

    # 2. Empty file
    if fi.size == 0:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk",
            reason="empty file (0 bytes)",
            confidence=1.0,
        )

    # 3. Known system junk names
    if name_lower in JUNK_NAMES:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk",
            reason=f"system-generated junk ({fi.path.name})",
            confidence=1.0,
        )

    # 4. Junk extensions
    if fi.ext in JUNK_EXTENSIONS:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk",
            reason=f"temporary/junk file type ({fi.ext})",
            confidence=0.95,
        )

    # 5. Old logs
    if fi.ext in LOG_EXTENSIONS and age_days > 7:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk",
            reason=f"log file {age_days:.0f} days old",
            confidence=0.90,
        )

    # 6. Installer files (used ones, past grace period)
    if fi.ext in INSTALLER_EXTENSIONS and age_days > installer_grace_days:
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,
            category="junk",
            reason=f"installer not used for {age_days:.0f} days",
            confidence=0.85,
        )

    # 7. Old files (not already junk)
    if age_days > old_threshold_days:
        return FileDecision(
            destination=Destination.OLD_FILES,
            category="old_file",
            reason=f"not modified in {age_days:.0f} days (threshold: {old_threshold_days})",
            confidence=0.80,
        )

    # 8. Vague / generic name — queue for AI
    if _is_vague_name(fi.path):
        return FileDecision(
            destination=Destination.DELETION_APPROVAL,  # tentative; AI may upgrade to KEEP
            category="vague",
            reason="generic/untitled filename — needs AI assessment",
            confidence=0.50,
            needs_ai=True,
        )

    # 9. No rule matched — keep
    return FileDecision(
        destination=Destination.KEEP,
        category="keep",
        reason="no cleanup rule matched",
    )
