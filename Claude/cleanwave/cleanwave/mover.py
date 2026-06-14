"""
mover.py — move files into subcategorised destination folders
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .models import FileInfo, FileDecision, Destination, MoveRecord
from .ui import console


def _resolve_collision(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    counter = 2
    while True:
        candidate = dest.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _dest_path(
    fi: FileInfo,
    dec: FileDecision,
    deletion_root: Path,
    old_files_root: Path,
) -> Path:
    """
    Build destination path.
    Structure: <root>/<subcategory>/<relative-path-from-home>/<filename>

    e.g. ~/Desktop/deletion_approval/installers/Downloads/old_app.dmg
         ~/Desktop/OLD_FILES/images/Pictures/2021/photo.jpg
    """
    home = Path.home()
    try:
        rel = fi.path.relative_to(home)
    except ValueError:
        rel = Path("outside_home") / fi.path.name

    base = deletion_root if dec.destination == Destination.DELETION_APPROVAL else old_files_root

    # subcategory subfolder — falls back to "other" if empty
    subdir = dec.subcategory or "other"

    filename = dec.new_name if dec.new_name else fi.path.name
    return base / subdir / rel.parent / filename


def execute_moves(
    decisions: list[tuple[FileInfo, FileDecision]],
    deletion_root: Path,
    old_files_root: Path,
    dry_run: bool = False,
) -> list[MoveRecord]:
    records: list[MoveRecord] = []

    if not dry_run:
        deletion_root.mkdir(parents=True, exist_ok=True)
        old_files_root.mkdir(parents=True, exist_ok=True)

    for fi, dec in decisions:
        if dec.destination == Destination.KEEP:
            continue

        dest = _dest_path(fi, dec, deletion_root, old_files_root)
        dest = _resolve_collision(dest)

        if not dry_run:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(fi.path), str(dest))
            except (OSError, PermissionError, shutil.Error) as e:
                console.print(f"[red]  ✗ could not move {fi.path.name}: {e}[/red]")
                continue

        records.append(MoveRecord(
            original=fi.path,
            destination=dest,
            category=dec.category,
            reason=dec.reason,
        ))

    return records
