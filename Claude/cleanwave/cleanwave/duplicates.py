"""
duplicates.py — SHA-256 based duplicate detection with parallel workers
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .models import FileInfo, FileDecision, Destination

BLOCK_SIZE = 65_536  # 64 KB read chunks


def _hash_file(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(BLOCK_SIZE):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def find_duplicates(
    files: list[FileInfo],
    workers: int = 4,
) -> list[tuple[FileInfo, FileDecision]]:
    """
    Hash all files in parallel, group by hash.
    For each group with >1 file: keep the NEWEST (highest mtime),
    mark the rest as duplicates destined for deletion_approval/.
    Returns a list of (FileInfo, FileDecision) for the duplicate copies only.
    """
    # Quick pre-filter: group by size — same hash requires same size
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for fi in files:
        by_size[fi.size].append(fi)

    # Only hash files that share a size with at least one other file
    candidates = [fi for group in by_size.values() if len(group) > 1 for fi in group]

    if not candidates:
        return []

    # Parallel hash
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_hash_file, fi.path): fi for fi in candidates}
        for fi in candidates:
            fi.hash_val = None  # reset
        for future in as_completed(futures):
            fi = futures[future]
            fi.hash_val = future.result()

    # Group by hash
    by_hash: dict[str, list[FileInfo]] = defaultdict(list)
    for fi in candidates:
        if fi.hash_val:
            by_hash[fi.hash_val].append(fi)

    results: list[tuple[FileInfo, FileDecision]] = []

    for hash_val, group in by_hash.items():
        if len(group) < 2:
            continue

        # Keep the most recently modified file
        group_sorted = sorted(group, key=lambda x: x.mtime, reverse=True)
        keeper = group_sorted[0]

        for dup in group_sorted[1:]:
            new_name = f"DUPLICATE_{dup.path.name}"
            results.append((dup, FileDecision(
                destination=Destination.DELETION_APPROVAL,
                category="duplicate",
                reason=f"identical content to {keeper.path} (keeping newest)",
                confidence=1.0,
                new_name=new_name,
            )))

    return results
