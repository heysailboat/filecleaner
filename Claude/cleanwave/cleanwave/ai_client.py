"""
ai_client.py — AI review pass over all flagged files.
Reviews rule-based decisions and overrides mistakes (e.g. screen savers
flagged as old files). AI is advisory — never the final word.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Callable

import requests

from .models import FileInfo, FileDecision, Destination

# ── Config ───────────────────────────────────────────────────────────────────

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

MAX_PREVIEW_CHARS = 300
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
    ".json", ".xml", ".csv", ".yaml", ".yml", ".sh", ".bat",
    ".c", ".cpp", ".h", ".java", ".rb", ".go", ".rs",
}

# Groq free tier: ~30 req/min. 2.5s between batches keeps us under.
_INTER_BATCH_DELAY = 2.5


def _read_preview(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(MAX_PREVIEW_CHARS)
    except OSError:
        return ""


def _build_review_prompt(batch: list[tuple[int, FileInfo, FileDecision]]) -> str:
    lines = [
        "You are reviewing automated file cleanup decisions on a user's computer.",
        "A rule-based classifier flagged these files for deletion or archiving.",
        "Your job is to catch mistakes — especially files wrongly flagged.",
        "Only set override=true if you're confident the rule got it wrong.",
        "Common mistakes to watch for: app resources, screen savers, system fonts,",
        "game files, or anything that looks like it belongs to an installed application.",
        "",
        "Respond ONLY with a valid JSON array, one object per file, in order:",
        '[{"index": N, "override": false, "correct_destination": "keep"|"deletion_approval"|"old_files", "reason": "brief"}]',
        "",
        "Files:",
    ]
    for idx, fi, dec in batch:
        last_activity = max(fi.mtime, fi.atime)
        age_days = (time.time() - last_activity) / 86400
        preview = _read_preview(fi.path)
        lines.append(f"\n--- [{idx}] ---")
        lines.append(f"Name: {fi.path.name}")
        lines.append(f"Path: {fi.path.parent}")
        lines.append(f"Extension: {fi.ext or 'none'}")
        lines.append(f"Size: {fi.size / 1024:.1f} KB")
        lines.append(f"Last activity: {age_days:.0f} days ago")
        lines.append(f"Rule decision: {dec.destination.value} ({dec.reason})")
        if preview:
            lines.append(f"Preview: {preview}")
    return "\n".join(lines)


def _call_api(prompt: str, api_key: str, provider: str) -> Optional[str]:
    url   = GROQ_URL        if provider == "groq" else OPENROUTER_URL
    model = GROQ_MODEL      if provider == "groq" else OPENROUTER_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800,
    }

    for attempt in range(5):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)

            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else min(60, 4 ** attempt)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        except requests.exceptions.HTTPError:
            if attempt < 4:
                time.sleep(2 ** attempt)
        except Exception:
            if attempt < 4:
                time.sleep(2 ** attempt)

    return None


def _parse_response(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    return data if isinstance(data, list) else []


def ai_review_decisions(
    items: list[tuple[FileInfo, FileDecision]],
    api_key: str,
    provider: str = "groq",
    batch_size: int = 10,
    on_batch_done: Optional[Callable[[int], None]] = None,
) -> list[tuple[FileInfo, FileDecision]]:
    """
    Reviews ALL flagged file decisions and overrides where the rule was wrong.
    AI receives the original rule decision + file metadata so it can sanity-check.
    On parse failure or API error, original rule decisions are preserved (safe).

    on_batch_done: optional callable(n_files) for progress bar updates.
    """
    if not items or not api_key:
        return items

    updated = list(items)

    _DEST_MAP = {
        "keep":               Destination.KEEP,
        "deletion_approval":  Destination.DELETION_APPROVAL,
        "old_files":          Destination.OLD_FILES,
    }

    for batch_num, start in enumerate(range(0, len(items), batch_size)):
        chunk = items[start: start + batch_size]
        indexed = [(start + i, fi, dec) for i, (fi, dec) in enumerate(chunk)]

        if batch_num > 0:
            time.sleep(_INTER_BATCH_DELAY)

        prompt = _build_review_prompt(indexed)
        raw = _call_api(prompt, api_key, provider)

        if raw is not None:
            try:
                results = _parse_response(raw)
                for item in results:
                    if not item.get("override", False):
                        continue
                    global_i = item.get("index")
                    if global_i is None or global_i >= len(updated):
                        continue
                    fi, dec = updated[global_i]
                    new_dest = _DEST_MAP.get(
                        item.get("correct_destination", "keep"),
                        Destination.KEEP,
                    )
                    updated[global_i] = (fi, FileDecision(
                        destination=new_dest,
                        category=dec.category,
                        subcategory=dec.subcategory,
                        reason=f"AI override: {item.get('reason', '')}",
                        confidence=0.70,
                        new_name=dec.new_name,
                    ))
            except Exception:
                pass  # parse failure → keep original rule decisions

        if on_batch_done is not None:
            on_batch_done(len(chunk))

    return updated
