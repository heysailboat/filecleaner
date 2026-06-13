from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from enum import Enum


class Destination(Enum):
    KEEP = "keep"
    DELETION_APPROVAL = "deletion_approval"
    OLD_FILES = "old_files"
    SKIP = "skip"


@dataclass
class FileInfo:
    path: Path
    size: int           # bytes
    mtime: float        # epoch
    ext: str            # lowercase, e.g. ".jpg"
    hash_val: Optional[str] = None


@dataclass
class FileDecision:
    destination: Destination
    category: str       # "junk", "duplicate", "old_file", "vague", "os_dir", "keep"
    reason: str
    confidence: float = 1.0
    needs_ai: bool = False
    new_name: Optional[str] = None   # used for DUPLICATE_ renaming


@dataclass
class SkippedDir:
    path: Path
    reason: str         # "os_system", "app_data", "permission_denied"


@dataclass
class ScanResult:
    files: list[FileInfo] = field(default_factory=list)
    skipped_dirs: list[SkippedDir] = field(default_factory=list)


@dataclass
class MoveRecord:
    original: Path
    destination: Path
    category: str
    reason: str
