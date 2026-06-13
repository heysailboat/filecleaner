"""
main.py — CLI entry point, orchestration, preview → confirm flow
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from pathlib import Path

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import yaml
    _YAML = True
except ImportError:
    _YAML = False

try:
    from plyer import notification as _plyer_notification
    _NOTIFY = True
except ImportError:
    _NOTIFY = False

from .models import Destination
from .scanner import collect_files
from .rules import classify
from .duplicates import find_duplicates
from .ai_client import assess_vague_files
from .ai_client import _INTER_BATCH_DELAY
from .mover import execute_moves
from .reporter import generate_report
from . import ui

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "old_file_threshold_days": 365,
    "installer_grace_days": 14,
    "deletion_dest": "~/Desktop/deletion_approval",
    "old_files_dest": "~/Desktop/OLD_FILES",
    "skip_hidden": False,
    "max_file_size_mb": 0,
    "ai_provider": "groq",
    "ai_batch_size": 10,
    "hash_workers": 4,
    "whitelist_patterns": [
        "*recovery*", "*password*", "*passphrase*", "*secret*",
        "*.key", "*.pem", "*.kdbx", "*.p12",
    ],
}


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if not path.exists():
        return cfg
    try:
        with open(path, "r") as f:
            if _YAML:
                loaded = yaml.safe_load(f) or {}
            else:
                import json
                loaded = json.load(f)
        cfg.update(loaded)
    except Exception as e:
        ui.console.print(f"[yellow]Warning: could not load config ({e}), using defaults[/yellow]")
    return cfg


def _notify(title: str, message: str) -> None:
    if not _NOTIFY:
        return
    try:
        _plyer_notification.notify(title=title, message=message, timeout=5)
    except Exception:
        pass


def _default_scan_dirs() -> list[str]:
    home = Path.home()
    candidates = ["Desktop", "Documents", "Downloads", "Movies", "Music", "Pictures"]
    existing = [str(home / d) for d in candidates if (home / d).exists()]
    return existing if existing else [str(home)]


def run(args: argparse.Namespace, cfg: dict) -> None:
    t0 = time.time()

    ui.print_banner()

    # ── Resolve scan directories ──────────────────────────────────────────
    if args.dir:
        scan_dirs = [str(Path(args.dir).expanduser().resolve())]
        ui.console.print(f"[dim]Scanning single directory: {scan_dirs[0]}[/dim]")
    elif args.home:
        scan_dirs = [str(Path.home())]
        ui.console.print("[dim]Scanning entire home directory[/dim]")
    else:
        scan_dirs = _default_scan_dirs()
        ui.console.print(f"[dim]Scanning: {', '.join(scan_dirs)}[/dim]")

    deletion_root = Path(cfg["deletion_dest"]).expanduser()
    old_files_root = Path(cfg["old_files_dest"]).expanduser()

    # ── Collect files ─────────────────────────────────────────────────────
    ui.print_section("Scanning")
    with ui.make_progress("Collecting files...") as prog:
        task = prog.add_task("Collecting files...", total=None)
        scan_result = collect_files(
            scan_dirs,
            skip_hidden=cfg["skip_hidden"],
            max_file_size_mb=cfg["max_file_size_mb"],
        )
        prog.update(task, total=1, completed=1)

    files = scan_result.files
    ui.console.print(f"  [green]✓[/green] {len(files)} files found, "
                     f"{len(scan_result.skipped_dirs)} directories skipped")
    ui.print_skipped_dirs(scan_result.skipped_dirs)

    # ── Rule-based classification ─────────────────────────────────────────
    ui.print_section("Classifying")
    rule_decisions: list[tuple] = []
    vague_queue: list[tuple] = []

    with ui.make_progress("Applying rules...") as prog:
        task = prog.add_task("Applying rules...", total=len(files))
        for fi in files:
            dec = classify(
                fi,
                old_threshold_days=cfg["old_file_threshold_days"],
                installer_grace_days=cfg["installer_grace_days"],
                extra_whitelist=cfg.get("whitelist_patterns", []),
            )
            if dec.needs_ai:
                vague_queue.append((fi, dec))
            else:
                rule_decisions.append((fi, dec))
            prog.advance(task)

    # ── Duplicate detection ───────────────────────────────────────────────
    ui.print_section("Duplicate detection")
    non_keep = [fi for fi, dec in rule_decisions if dec.destination != Destination.KEEP]
    with ui.make_progress("Hashing files...") as prog:
        task = prog.add_task("Hashing files...", total=len(non_keep))
        # Run synchronously but show progress (parallel happens inside)
        dup_decisions = find_duplicates(non_keep, workers=cfg["hash_workers"])
        prog.update(task, completed=len(non_keep))

    # Remove files now marked as duplicates from rule_decisions to avoid double-entry
    dup_paths = {fi.path for fi, _ in dup_decisions}
    rule_decisions = [(fi, dec) for fi, dec in rule_decisions if fi.path not in dup_paths]

    ui.console.print(f"  [green]✓[/green] {len(dup_decisions)} duplicate copies found")

    # ── AI advisory pass ──────────────────────────────────────────────────
    ai_decisions: list[tuple] = []
    if vague_queue:
        ui.print_section("AI assessment (advisory)")
        api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        provider = "groq" if os.environ.get("GROQ_API_KEY") else "openrouter"

        if api_key:
            n_batches = (len(vague_queue) + cfg["ai_batch_size"] - 1) // cfg["ai_batch_size"]
            eta_min = (n_batches * _INTER_BATCH_DELAY) / 60
            ui.console.print(
                f"  [dim]Sending {len(vague_queue)} files to {provider} "
                f"({n_batches} batches, ~{eta_min:.1f} min at free-tier rate)…[/dim]"
            )
            with ui.make_progress("AI assessing...") as prog:
                task = prog.add_task("AI assessing...", total=len(vague_queue))

                def _on_batch(n: int) -> None:
                    prog.advance(task, n)

                ai_decisions = assess_vague_files(
                    vague_queue,
                    api_key=api_key,
                    provider=provider,
                    batch_size=cfg["ai_batch_size"],
                    on_batch_done=_on_batch,
                )
        else:
            ui.console.print("  [yellow]No API key found — vague files moved to deletion_approval for manual review[/yellow]")
            ai_decisions = vague_queue  # stay as-is (deletion_approval, human decides)

    # ── Merge all decisions ───────────────────────────────────────────────
    all_decisions = rule_decisions + dup_decisions + ai_decisions

    # Only show things that will actually move
    actionable = [(fi, dec) for fi, dec in all_decisions if dec.destination != Destination.KEEP]

    # ── Preview ───────────────────────────────────────────────────────────
    ui.print_section("Preview")
    if actionable:
        table = ui.build_preview_table(actionable)
        ui.console.print(table)
    else:
        ui.console.print("  [green]Nothing flagged — your files look clean![/green]")
        return

    # ── Confirm ───────────────────────────────────────────────────────────
    if not ui.confirm_proceed(len(actionable)):
        ui.console.print("[dim]Aborted — nothing moved.[/dim]")
        return

    # ── Execute moves ─────────────────────────────────────────────────────
    ui.print_section("Moving files")
    with ui.make_progress("Moving...") as prog:
        task = prog.add_task("Moving...", total=len(actionable))
        records = execute_moves(
            actionable,
            deletion_root=deletion_root,
            old_files_root=old_files_root,
            dry_run=args.dry_run,
        )
        prog.update(task, completed=len(actionable))

    # ── Report ────────────────────────────────────────────────────────────
    report_dir = Path.home() / ".cleanwave"
    report_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"cleanwave_{stamp}.md"

    generate_report(
        moved=records,
        skipped_dirs=scan_result.skipped_dirs,
        scan_dirs=scan_dirs,
        duration=time.time() - t0,
        output_path=report_path,
        dry_run=args.dry_run,
    )

    duration = time.time() - t0
    ui.print_summary(records, scan_result.skipped_dirs, duration, report_path)
    _notify("CleanWave done", f"Moved {len(records)} files in {duration:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cleanwave",
        description="AI-assisted file cleanup — moves files for your review, never deletes.",
    )

    target = parser.add_mutually_exclusive_group()
    target.add_argument("--dir", metavar="PATH",
                        help="Scan a single specific directory")
    target.add_argument("--home", action="store_true",
                        help="Scan entire home directory (slower)")

    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — don't actually move anything")
    parser.add_argument("--config", metavar="PATH",
                        help="Path to config YAML (default: ~/.cleanwave/config.yaml)")
    parser.add_argument("--old-days", type=int,
                        help="Days before a file is 'old' (overrides config)")

    args = parser.parse_args()

    config_path = Path(args.config) if args.config else Path.home() / ".cleanwave" / "config.yaml"
    cfg = load_config(config_path)

    if args.old_days:
        cfg["old_file_threshold_days"] = args.old_days

    if args.dry_run:
        ui.console.print("[yellow bold]DRY RUN — no files will be moved[/yellow bold]")

    try:
        run(args, cfg)
    except KeyboardInterrupt:
        ui.console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(0)
