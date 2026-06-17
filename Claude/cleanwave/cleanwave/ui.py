"""
ui.py — terminal display, CleanWave character, progress wrappers
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, MofNCompleteColumn, TimeRemainingColumn,
)
from rich.prompt import Confirm

from .models import FileDecision, Destination, MoveRecord

console = Console()

# ── Wave character frames ────────────────────────────────────────────────────
WAVE_FRAMES = ["⠀🌊 ", "~🌊 ", "~~🌊", "~🌊 "]

BANNER = r"""
   ___ _                _    _
  / __| |___ __ _ _ _  | |  | |__ _ __  ___ 
 | (__| / -_) _` | ' \ | |/\| / _` \ \ / / -_)
  \___|_\___\__,_|_||_||__/\__\__,_|/_\_/\___|
"""


def print_banner() -> None:
    console.print(Panel(
        Text(BANNER, style="bold cyan", justify="center"),
        subtitle="[dim]AI-assisted file cleanup, made by AI[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))


def make_progress(description: str = "Working...") -> Progress:
    """Reusable progress bar with the wave spinner."""
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        BarColumn(bar_width=36, style="cyan", complete_style="bold cyan"),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


def print_section(title: str) -> None:
    console.print(f"\n[bold cyan]{'─' * 4} {title} {'─' * (40 - len(title))}[/bold cyan]")


def print_skipped_dirs(skipped: list) -> None:
    if not skipped:
        return
    print_section("Skipped directories (OS / app-related)")
    for sd in skipped:
        console.print(f"  [dim yellow]⚠[/dim yellow]  [dim]{sd.path}[/dim]  [dim]({sd.reason})[/dim]")


def build_preview_table(decisions: list[tuple]) -> Table:
    """
    decisions: list of (FileInfo, FileDecision)
    Returns a Rich Table showing what would move where.
    """
    table = Table(
        title="[bold]Preview — nothing has moved yet[/bold]",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
        expand=True,
    )
    table.add_column("File", no_wrap=False, ratio=4)
    table.add_column("Category", ratio=1)
    table.add_column("Destination", ratio=2)
    table.add_column("Reason", ratio=3)

    cat_colors = {
        "junk":       "red",
        "duplicate":  "yellow",
        "old_file":   "dark_orange",
        "vague":      "magenta",
    }

    dest_labels = {
        Destination.DELETION_APPROVAL: "[red]deletion_approval/[/red]",
        Destination.OLD_FILES:         "[dark_orange]OLD_FILES/[/dark_orange]",
        Destination.KEEP:              "[green]keep[/green]",
    }

    for fi, dec in decisions:
        color = cat_colors.get(dec.category, "white")
        display_name = dec.new_name or fi.path.name
        table.add_row(
            f"[dim]{str(fi.path.parent)}/[/dim][bold]{display_name}[/bold]",
            f"[{color}]{dec.category}[/{color}]",
            dest_labels.get(dec.destination, str(dec.destination)),
            f"[dim]{dec.reason}[/dim]",
        )
    return table


def print_summary(
    moved: list[MoveRecord],
    skipped_dirs: list,
    duration: float,
    report_path: Path,
) -> None:
    deletion = [m for m in moved if "deletion_approval" in str(m.destination)]
    old       = [m for m in moved if "OLD_FILES" in str(m.destination)]

    console.print()
    console.print(Panel(
        f"[bold green]✓ Done![/bold green]  "
        f"[cyan]{len(deletion)}[/cyan] → deletion_approval   "
        f"[dark_orange]{len(old)}[/dark_orange] → OLD_FILES   "
        f"[dim]{len(skipped_dirs)} dirs skipped   {duration:.1f}s[/dim]\n"
        f"[dim]Report → {report_path}[/dim]",
        border_style="green",
    ))


def confirm_proceed(n: int) -> bool:
    if n == 0:
        console.print("[green]Nothing to move — you're already clean![/green]")
        return False
    return Confirm.ask(
        f"\n[bold]Move {n} item(s) as shown above?[/bold]",
        default=False,
    )
