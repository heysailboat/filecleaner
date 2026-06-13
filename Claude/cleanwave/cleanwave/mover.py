"""
mover.py — move files to deletion_approval/ or OLD_FILES/ with collision handling
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .models import FileInfo, FileDecision, Destination, MoveRecord
from .ui import console


def _resolve_collision(dest: Path) -> Path:
    """If dest already exists, append _2, _3, ... until free."""
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
    Compute destination path, preserving the file's directory structure
    relative to home so it's traceable after the move.
    """
    home = Path.home()
    try:
        rel = fi.path.relative_to(home)
    except ValueError:
        # File outside home (e.g. external drive, root-level paths)
        rel = Path("outside_home") / fi.path.name

    if dec.destination == Destination.DELETION_APPROVAL:
        base = deletion_root
    else:
        base = old_files_root

    # For duplicates, use the renamed filename but preserve parent dirs
    filename = dec.new_name if dec.new_name else fi.path.name
    return base / rel.parent / filename


def execute_moves(
    decisions: list[tuple[FileInfo, FileDecision]],
    deletion_root: Path,
    old_files_root: Path,
    dry_run: bool = False,
) -> list[MoveRecord]:
    """
    Move files based on their decisions.
    Skips KEEP decisions silently.
    Returns list of MoveRecord for reporting.
    """
    records: list[MoveRecord] = []

    # Create destination roots
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
                console.print(f"[red]  ✗ Could not move {fi.path.name}: {e}[/red]")
                continue

        records.append(MoveRecord(
            original=fi.path,
            destination=dest,
            category=dec.category,
            reason=dec.reason,
        ))

    return records
