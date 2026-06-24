"""
main.py — CLI entry point and orchestration
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import time
from pathlib import Path

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
from .ai_client import ai_review_decisions, _INTER_BATCH_DELAY
from .mover import execute_moves
from .reporter import generate_report
from . import cache as cache_mod
from . import ui

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
            loaded = (yaml.safe_load(f) if _YAML else json.load(f)) or {}
        cfg.update(loaded)
    except Exception as e:
        ui.console.print(f"[yellow]warning: couldn't load config ({e}), using defaults[/yellow]")
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


def _parse_since(value: str) -> float:
    """Parse a YYYY-MM-DD string into an epoch timestamp."""
    import datetime as dt
    try:
        d = dt.datetime.strptime(value, "%Y-%m-%d")
        return d.timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date '{value}' — use YYYY-MM-DD format (e.g. 2023-01-01)"
        )


# ── undo ─────────────────────────────────────────────────────────────────────

def run_undo(report_dir: Path) -> None:
    """Find the most recent JSON sidecar and restore all files in it."""
    from .mover import _resolve_collision
    
    sidecars = sorted(report_dir.glob("cleanwave_*.json"), reverse=True)

    if not sidecars:
        ui.console.print("[yellow]no undo history found in ~/.cleanwave/[/yellow]")
        return

    # show options if more than one
    if len(sidecars) == 1:
        chosen = sidecars[0]
    else:
        ui.console.print("\navailable runs to undo:\n")
        for i, s in enumerate(sidecars[:10]):
            mtime = datetime.datetime.fromtimestamp(s.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            try:
                count = len(json.loads(s.read_text())["items"] if "items" in
                            json.loads(s.read_text()) else json.loads(s.read_text()))
            except Exception:
                count = "?"
            ui.console.print(f"  [{i}] {mtime}  ({count} files)  {s.name}")

        raw = ui.console.input("\n[bold]which run to undo? (0 = most recent, q = quit):[/bold] ").strip()
        if raw.lower() == "q":
            return
        try:
            chosen = sidecars[int(raw)]
        except (ValueError, IndexError):
            ui.console.print("[red]invalid choice[/red]")
            return

    try:
        records = json.loads(chosen.read_text(encoding="utf-8"))
    except Exception as e:
        ui.console.print(f"[red]couldn't read sidecar: {e}[/red]")
        return

    # handle both old flat list and new dict format
    if isinstance(records, dict):
        records = records.get("items", [])

    restored, failed = 0, 0
    ui.print_section("Undoing")

    home = Path.home()

    for entry in records:
        # validate record structure before touching the filesystem
        if not isinstance(entry, dict):
            ui.console.print("  [yellow]⚠[/yellow] skipping malformed entry (not a dict)")
            failed += 1
            continue

        moved_to = entry.get("moved_to")
        original = entry.get("original")

        if not isinstance(moved_to, str) or not isinstance(original, str):
            ui.console.print("  [yellow]⚠[/yellow] skipping malformed entry (missing/invalid keys)")
            failed += 1
            continue

        src  = Path(moved_to)
        dest = Path(original)

        # src must be under home — refuse to touch anything outside
        try:
            src.resolve().relative_to(home.resolve())
        except ValueError:
            ui.console.print(f"  [red]✗[/red] refusing: src outside home: {src}")
            failed += 1
            continue

        # dest must also be under home
        try:
            dest.resolve().relative_to(home.resolve())
        except ValueError:
            ui.console.print(f"  [red]✗[/red] refusing: dest outside home: {dest}")
            failed += 1
            continue

        if not src.exists():
            ui.console.print(f"  [yellow]⚠[/yellow] already gone: {src.name}")
            failed += 1
            continue

        # avoid silently overwriting anything already at the destination
        dest = _resolve_collision(dest)

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            ui.console.print(f"  [green]✓[/green] restored {dest.name}")
            restored += 1
        except Exception as e:
            ui.console.print(f"  [red]✗[/red] {src.name}: {e}")
            failed += 1

    ui.console.print(
        f"\n  [green]{restored} restored[/green]"
        + (f"  [yellow]{failed} failed[/yellow]" if failed else "")
    )


# ── main run ──────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace, cfg: dict) -> None:
    t0 = time.time()

    ui.print_banner()

    # resolve scan dirs
    if args.dir:
        scan_dirs = [str(Path(args.dir).expanduser().resolve())]
        ui.console.print(f"[dim]scanning: {scan_dirs[0]}[/dim]")
    elif args.home:
        scan_dirs = [str(Path.home())]
        ui.console.print("[dim]scanning entire home directory[/dim]")
    else:
        scan_dirs = _default_scan_dirs()
        ui.console.print(f"[dim]scanning: {', '.join(scan_dirs)}[/dim]")

    deletion_root  = Path(cfg["deletion_dest"]).expanduser()
    old_files_root = Path(cfg["old_files_dest"]).expanduser()

    since_ts = _parse_since(args.since) if args.since else None

    # ── cache check (real runs only) ─────────────────────────────────────
    actionable = None
    if not args.dry_run:
        hit = cache_mod.load_fresh(scan_dirs)
        if hit:
            actionable, created_at = hit
            age_min = (time.time() - created_at) / 60
            ui.console.print(
                f"\n  [green]✓[/green] using cached dry-run results "
                f"from {age_min:.0f} min ago ({len(actionable)} files) — "
                f"skipping scan + AI"
            )

    if actionable is None:
        # ── collect ──────────────────────────────────────────────────────
        ui.print_section("Scanning")
        with ui.make_progress("collecting files...") as prog:
            task = prog.add_task("collecting files...", total=None)
            scan_result = collect_files(
                scan_dirs,
                skip_hidden=cfg["skip_hidden"],
                max_file_size_mb=cfg["max_file_size_mb"],
            )
            prog.update(task, total=1, completed=1)

        files = scan_result.files
        ui.console.print(
            f"  [green]✓[/green] {len(files)} files found, "
            f"{len(scan_result.skipped_dirs)} dirs skipped"
        )
        ui.print_skipped_dirs(scan_result.skipped_dirs)

        # ── rules ────────────────────────────────────────────────────────
        ui.print_section("Classifying")
        rule_decisions: list[tuple] = []
        with ui.make_progress("applying rules...") as prog:
            task = prog.add_task("applying rules...", total=len(files))
            for fi in files:
                dec = classify(
                    fi,
                    old_threshold_days=cfg["old_file_threshold_days"],
                    installer_grace_days=cfg["installer_grace_days"],
                    extra_whitelist=cfg.get("whitelist_patterns", []),
                    since_timestamp=since_ts,
                )
                rule_decisions.append((fi, dec))
                prog.advance(task)

        # ── duplicates ───────────────────────────────────────────────────
        ui.print_section("Duplicate detection")
        all_files = [fi for fi, _ in rule_decisions]
        with ui.make_progress("hashing files...") as prog:
            task = prog.add_task("hashing files...", total=len(all_files))
            dup_decisions = find_duplicates(all_files, workers=cfg["hash_workers"])
            prog.update(task, completed=len(all_files))

        dup_paths = {fi.path for fi, _ in dup_decisions}
        rule_decisions = [(fi, dec) for fi, dec in rule_decisions if fi.path not in dup_paths]
        ui.console.print(f"  [green]✓[/green] {len(dup_decisions)} duplicate copies found")

        all_decisions = rule_decisions + dup_decisions
        actionable = [(fi, dec) for fi, dec in all_decisions if dec.destination != Destination.KEEP]

        # ── AI review ────────────────────────────────────────────────────
        ui.print_section("AI review")
        api_key  = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        provider = "groq" if os.environ.get("GROQ_API_KEY") else "openrouter"

        if api_key and actionable:
            n_batches = (len(actionable) + cfg["ai_batch_size"] - 1) // cfg["ai_batch_size"]
            eta_min   = (n_batches * _INTER_BATCH_DELAY) / 60
            ui.console.print(
                f"  [dim]reviewing {len(actionable)} flagged files "
                f"({n_batches} batches, ~{eta_min:.1f} min)…[/dim]"
            )
            with ui.make_progress("AI reviewing...") as prog:
                task = prog.add_task("AI reviewing...", total=len(actionable))
                def _on_batch(n: int) -> None:
                    prog.advance(task, n)
                actionable = ai_review_decisions(
                    actionable,
                    api_key=api_key,
                    provider=provider,
                    batch_size=cfg["ai_batch_size"],
                    on_batch_done=_on_batch,
                )
        elif not api_key:
            ui.console.print("  [yellow]no API key — skipping AI review[/yellow]")

        actionable = [(fi, dec) for fi, dec in actionable if dec.destination != Destination.KEEP]

    else:
        # cache hit — we still need scan_result for skipped dirs in report
        scan_result = type("_SR", (), {"skipped_dirs": []})()

    # ── nothing to do ────────────────────────────────────────────────────
    if not actionable:
        ui.console.print("\n  [green]nothing to move — you're clean![/green]")
        return

    # ── dry run ──────────────────────────────────────────────────────────
    if args.dry_run:
        from .preview_html import generate_and_open
        ui.print_section("Dry run — opening preview in browser")
        out = generate_and_open(actionable, scan_dirs)
        ui.console.print(f"  [dim]saved → {out}[/dim]")

        # save cache so the next real run can skip all this
        cache_path = cache_mod.save(actionable, scan_dirs)
        ui.console.print(
            f"  [dim]results cached → {cache_path.name} "
            f"(valid 2h — next run will skip scan + AI)[/dim]"
        )
        ui.console.print("  [dim]run without --dry-run when ready.[/dim]")
        return

    # ── real run: localhost confirm ───────────────────────────────────────
    from .confirm_server import run_confirm
    ui.print_section("Review in browser")
    ui.console.print(
        "  [dim]opening http://127.0.0.1:7234 — "
        "uncheck anything you want to skip, then confirm[/dim]"
    )
    confirmed = run_confirm(actionable)

    if confirmed is None:
        ui.console.print("[dim]cancelled — nothing moved.[/dim]")
        return

    ui.console.print(f"  [green]✓[/green] confirmed {len(confirmed)} of {len(actionable)} files")

    # clear cache now that we're actually moving stuff
    cache_mod.clear(scan_dirs)

    # ── move ─────────────────────────────────────────────────────────────
    ui.print_section("Moving files")
    with ui.make_progress("moving...") as prog:
        task = prog.add_task("moving...", total=len(confirmed))
        records = execute_moves(
            confirmed,
            deletion_root=deletion_root,
            old_files_root=old_files_root,
        )
        prog.update(task, completed=len(confirmed))

    # ── report ───────────────────────────────────────────────────────────
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
    )

    duration = time.time() - t0
    ui.print_summary(records, scan_result.skipped_dirs, duration, report_path)
    _notify("cleanwave done", f"moved {len(records)} files in {duration:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cleanwave",
        description="AI-assisted file cleanup — moves files for review, never deletes.",
    )

    target = parser.add_mutually_exclusive_group()
    target.add_argument("--dir",  metavar="PATH", help="scan a single directory")
    target.add_argument("--home", action="store_true", help="scan entire home directory")

    parser.add_argument("--dry-run",  action="store_true", help="preview only, nothing moves")
    parser.add_argument("--config",   metavar="PATH",      help="path to config yaml")
    parser.add_argument("--old-days", type=int,            help="override old-file threshold (days)")
    parser.add_argument("--since",    metavar="YYYY-MM-DD",
                        help="flag files with no activity since this date")
    parser.add_argument("--undo",     action="store_true",
                        help="restore files from a previous run")

    args = parser.parse_args()

    config_path = Path(args.config) if args.config else Path.home() / ".cleanwave" / "config.yaml"
    cfg = load_config(config_path)

    if args.old_days:
        cfg["old_file_threshold_days"] = args.old_days

    report_dir = Path.home() / ".cleanwave"

    if args.undo:
        ui.print_banner()
        run_undo(report_dir)
        return

    if args.dry_run:
        ui.console.print("[yellow bold]dry run — nothing will be moved[/yellow bold]")

    try:
        run(args, cfg)
    except KeyboardInterrupt:
        ui.console.print("\n[dim]interrupted.[/dim]")
        sys.exit(0)
